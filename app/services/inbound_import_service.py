"""
入库CSV批量导入服务
"""
from typing import Tuple, List, Dict
from sqlalchemy.orm import Session
from app.models import Material, Location, InboundOrder
from app.services.inbound_service import InboundService
from app.utils.logger import logger


class InboundImportService:

    @staticmethod
    def import_from_csv(
        file_content: bytes,
        operator_id: int,
        db: Session
    ) -> dict:
        """
        从 CSV 内容批量创建入库单

        参数：
        - file_content: CSV 文件二进制内容（UTF-8编码）
        - operator_id: 操作人ID
        - db: 数据库会话

        返回：
        {"imported": N, "failed": M, "errors": [{"row": 2, "error": "..."}, ...]}
        """
        import csv
        import io

        content = file_content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))

        imported = 0
        failed = 0
        errors = []

        for idx, row in enumerate(reader, start=1):
            try:
                result = InboundImportService._process_row(row, operator_id, db)
                if result["success"]:
                    imported += 1
                else:
                    failed += 1
                    errors.append({"row": idx + 1, "error": result["error"]})
            except Exception as e:
                failed += 1
                errors.append({"row": idx + 1, "error": str(e)})
                logger.error(f"导入CSV第{idx + 1}行异常: {str(e)}")

        return {
            "imported": imported,
            "failed": failed,
            "errors": errors
        }

    @staticmethod
    def _process_row(row: dict, operator_id: int, db: Session) -> dict:
        """
        处理 CSV 中的一行，创建入库单。

        CSV 列（支持中英文列名）：
        - material_code / 物料编码
        - material_name / 物料名称（当编码为空时的备选）
        - quantity / 数量（必填）
        - location_code / 库位编码（可选）
        - supplier / 供应商（可选）
        - batch_info / 批次信息（可选）
        - remark / 备注（可选）
        - specification / 规格型号（可选）
        - unit / 单位（可选）
        """
        # 解析数量（必填）
        qty_str = (row.get("quantity") or row.get("数量") or "").strip()
        if not qty_str:
            return {"success": False, "error": "缺少数量(quantity)"}
        try:
            quantity = float(qty_str)
        except ValueError:
            return {"success": False, "error": f"数量格式错误: {qty_str}"}
        if quantity <= 0:
            return {"success": False, "error": f"数量必须大于0: {quantity}"}

        # 解析物料
        material_code = (row.get("material_code") or row.get("物料编码") or "").strip()
        material_name = (row.get("material_name") or row.get("物料名称") or "").strip()

        material_id = None
        name_text = None
        spec_text = row.get("specification") or row.get("规格型号") or None
        unit_text = row.get("unit") or row.get("单位") or None

        if material_code:
            material = db.query(Material).filter(
                Material.code == material_code
            ).first()
            if material:
                material_id = material.id
            else:
                return {"success": False, "error": f"物料编码不存在: {material_code}"}
        elif material_name:
            # 尝试精确匹配物料名称
            material = db.query(Material).filter(
                Material.name == material_name
            ).first()
            if material:
                material_id = material.id
            else:
                name_text = material_name
        else:
            return {"success": False, "error": "缺少物料编码(material_code)或物料名称(material_name)"}

        # 解析库位（可选）
        location_code = (row.get("location_code") or row.get("库位编码") or "").strip()
        location_id = None
        if location_code:
            location = db.query(Location).filter(
                Location.code == location_code
            ).first()
            if location:
                location_id = location.id
            else:
                return {"success": False, "error": f"库位编码不存在: {location_code}"}

        # 其他可选字段
        supplier = row.get("supplier") or row.get("供应商") or None
        batch_info = row.get("batch_info") or row.get("批次信息") or None
        remark = row.get("remark") or row.get("备注") or None

        # 调用现有服务创建入库单
        success, msg, order = InboundService.create_inbound_order(
            inbound_type="procurement",
            quantity=quantity,
            material_id=material_id,
            material_name_text=name_text,
            specification_text=spec_text,
            unit_text=unit_text,
            location_id=location_id,
            supplier=supplier,
            batch_info=batch_info,
            reason=remark,
            operator_id=operator_id,
            db=db
        )

        if not success:
            return {"success": False, "error": msg}

        # 设置状态为 pending_review（等待到货确认），而非默认的 draft
        if order and order.status == 'draft':
            order.status = 'pending_arrival'

        db.commit()

        logger.info(f"CSV导入创建入库单成功 | 行: 物料={material_code or material_name} | 数量={quantity}")
        return {"success": True}
