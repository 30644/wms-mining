"""
审批中心API路由
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import datetime

from app.database import get_db
from app.models import User, InboundOrder, OutboundOrder, Request
from app.models.business import TransferOrder, ScrapOrder, ReturnOrder
from app.models.purchase import PurchaseOrder
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.utils.business_tools import PermissionService
from app.utils.logger import logger

router = APIRouter()


def _query_approvals(db: Session, model, status_filter, id_prefix, biz_type,
                     title_fmt, no_field='no', applicant_attr='creator'):
    """通用查询待审批单据，异常时返回空列表"""
    try:
        results = []
        for o in db.query(model).filter(model.status == status_filter).all():
            no = getattr(o, no_field, '')
            applicant = None
            rel = getattr(o, applicant_attr, None)
            if rel:
                applicant = getattr(rel, 'real_name', None) or getattr(rel, 'name', '')
            created = o.created_at
            mat = getattr(o, 'material', None)
            # 支持 items 关联（调拨单、报废单等）
            items = getattr(o, 'items', None)
            if not mat and items and len(items) > 0:
                mat = items[0].material
            total_qty = 0
            material_names = []
            if items:
                for item in items:
                    qty = float(getattr(item, 'quantity', 0) or 0)
                    total_qty += qty
                    if item.material:
                        material_names.append(item.material.name or '')
            base = {
                'id': f"{id_prefix}_{o.id}", 'type': biz_type,
                'business_no': no,
                'title': title_fmt.format(no=no),
                'applicant_name': applicant or '',
                'apply_date': created.isoformat()[:10] if created else '',
                'created_at': created.isoformat() if created else '',
                'status': 'pending', 'current_approver': '待审批',
                'material_name': ', '.join(material_names[:3]) if material_names else (mat.name if mat else None),
                'specification_text': getattr(o, 'specification_text', None) or (mat.specification if mat else None),
                'unit_text': getattr(o, 'unit_text', None) or (mat.unit if mat else None),
                'quantity': float(total_qty) if total_qty > 0 else float(getattr(o, 'quantity', 0) or 0),
                'reason': getattr(o, 'reason', None) or getattr(o, 'remark', None) or '',
            }
            # 直接领用补充字段
            di_qty = getattr(o, 'direct_issue_quantity', None)
            if di_qty:
                base['direct_issue_quantity'] = float(di_qty)
            # 入库单显示存储数量（总量 - 直领量）
            if biz_type == 'inbound' and di_qty:
                base['quantity'] = max(0.0, base['quantity'] - float(di_qty))
                base['total_quantity'] = float(getattr(o, 'quantity', 0) or 0)
            results.append(base)
        return results
    except Exception as e:
        logger.warning(f"查询[{biz_type}]待审批列表异常: {str(e)}")
        return []


def _get_pending_approvals(db: Session, current_user: User):
    """获取待审批列表"""
    approvals = []

    # 入库单审批（到货审核员和库管都能看到）
    if PermissionService.check_role(current_user.id, 'receiving_inspector', db) or \
       PermissionService.check_role(current_user.id, 'warehouse_manager', db) or \
       PermissionService.check_role(current_user.id, 'super_admin', db):
        approvals += _query_approvals(
            db, InboundOrder, 'pending_review', 'inbound', 'inbound',
            '到货单 {no} 验收', no_field='inbound_no', applicant_attr='operator',
        )

    # 库管领导审批领料申请
    if PermissionService.check_role(current_user.id, 'warehouse_manager', db) or \
       PermissionService.check_role(current_user.id, 'super_admin', db):
        approvals += _query_approvals(
            db, Request, 'pending_leader_review', 'request', 'outbound',
            '领料申请 {no}', no_field='request_no', applicant_attr='requester',
        )

    # 调拨单审批
    if PermissionService.check_role(current_user.id, 'warehouse_manager', db) or \
       PermissionService.check_role(current_user.id, 'super_admin', db):
        approvals += _query_approvals(
            db, TransferOrder, 'pending_approval', 'transfer', 'transfer',
            '调拨单 {no}', no_field='transfer_no',
        )

    # 报废单审批
    if PermissionService.check_role(current_user.id, 'warehouse_manager', db) or \
       PermissionService.check_role(current_user.id, 'super_admin', db):
        approvals += _query_approvals(
            db, ScrapOrder, 'pending_approval', 'scrap', 'scrap',
            '报废单 {no}', no_field='scrap_no',
        )

    # 退货单审批
    if PermissionService.check_role(current_user.id, 'warehouse_manager', db) or \
       PermissionService.check_role(current_user.id, 'super_admin', db):
        approvals += _query_approvals(
            db, ReturnOrder, 'pending_approval', 'return', 'return',
            '退货单 {no}', no_field='return_no',
        )

    # 采购清单审批（三级流转：班长→技术员→审核员）
    from app.services.purchase_service import PurchaseService
    approvals += PurchaseService.get_pending_approvals_for_role(
        db, current_user.role
    )

    return approvals


@router.get('/list', summary='获取审批列表')
async def get_approval_list(
    type: Optional[str] = Query(None, description='审批类型'),
    status: Optional[str] = Query(None, description='审批状态'),
    start_date: Optional[str] = Query(None, description='开始日期'),
    end_date: Optional[str] = Query(None, description='结束日期'),
    sort_by: Optional[str] = Query('created_at', description='排序字段'),
    sort_order: Optional[str] = Query('desc', description='排序方向: asc/desc'),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # pending 状态走待审批列表
        if status in (None, '', 'pending'):
            all_approvals = _get_pending_approvals(db, current_user)

            if type:
                all_approvals = [a for a in all_approvals if a['type'] == type]
            if status == 'pending':
                all_approvals = [a for a in all_approvals if a['status'] == 'pending']

            # 排序
            reverse = sort_order != 'asc'
            if sort_by == 'created_at':
                all_approvals.sort(key=lambda x: x.get('created_at', ''), reverse=reverse)

            total = len(all_approvals)
            start_idx = (page - 1) * size
            items = all_approvals[start_idx:start_idx + size]

            return APIResponse(code=0, message='获取成功', data={'list': items, 'total': total})

        # 非 pending 状态（approved/rejected）查询已处理的票据
        all_approvals = []
        filter_type = type or None

        # 入库单已通过/已驳回
        if not filter_type or filter_type == 'inbound':
            status_map = {'approved': 'approved,completed,pending_inbound_review',
                          'rejected': 'rejected,cancelled'}
            target_statuses = status_map.get(status, status)
            target_list = [s.strip() for s in target_statuses.split(',')]
            for s in target_list:
                for o in db.query(InboundOrder).filter(InboundOrder.status == s).all():
                    created = o.created_at
                    mat = getattr(o, 'material', None)
                    all_approvals.append({
                        'id': f"inbound_{o.id}", 'type': 'inbound',
                        'business_no': o.inbound_no or '',
                        'title': f"入库单 {o.inbound_no or ''}",
                        'applicant_name': o.operator.real_name if o.operator else '',
                        'apply_date': created.isoformat()[:10] if created else '',
                        'created_at': created.isoformat() if created else '',
                        'reason': o.reason or '',
                        'status': 'approved' if s in ('approved', 'completed', 'pending_inbound_review') else 'rejected',
                        'current_approver': '',
                        'material_name': mat.name if mat else None,
                        'specification_text': getattr(o, 'specification_text', None) or (mat.specification if mat else None),
                        'unit_text': getattr(o, 'unit_text', None) or (mat.unit if mat else None),
                        'quantity': float(o.quantity),
                        'direct_issue_quantity': float(o.direct_issue_quantity) if o.direct_issue_quantity else None,
                        'outbound_order_no': o.outbound_order.outbound_no if o.outbound_order else None,
                    })

        # 采购清单已通过/已驳回
        if not filter_type or filter_type == 'purchase':
            target_status = 'approved,completed,rejected,cancelled'
            target_list = [s.strip() for s in target_status.split(',')]
            for s in target_list:
                for o in db.query(PurchaseOrder).filter(PurchaseOrder.status == s).all():
                    mat = o.material
                    created = o.created_at
                    is_approved = s in ('approved', 'completed')
                    all_approvals.append({
                        'id': f"purchase_{o.id}", 'type': 'purchase',
                        'business_no': o.purchase_no,
                        'title': f"采购申请 {o.purchase_no}",
                        'applicant_name': o.applicant.real_name if o.applicant else '',
                        'apply_date': created.isoformat()[:10] if created else '',
                        'created_at': created.isoformat() if created else '',
                        'reason': o.review_comment or '',
                        'status': 'approved' if is_approved else 'rejected',
                        'current_approver': '',
                        'material_name': mat.name if mat else None,
                        'specification_text': mat.specification if mat else None,
                        'unit_text': mat.unit if mat else None,
                        'quantity': float(o.quantity),
                    })

        # 排序
        reverse = sort_order != 'asc'
        if sort_by == 'created_at':
            all_approvals.sort(key=lambda x: x.get('created_at', ''), reverse=reverse)

        total = len(all_approvals)
        start_idx = (page - 1) * size
        items = all_approvals[start_idx:start_idx + size]

        return APIResponse(code=0, message='获取成功', data={'list': items, 'total': total})
    except Exception as e:
        logger.error(f"获取审批列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'获取审批列表失败: {str(e)}')


@router.get('/pending', summary='获取待审批列表')
async def get_pending_list(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        all_approvals = _get_pending_approvals(db, current_user)
        pending = [a for a in all_approvals if a['status'] == 'pending']
        total = len(pending)
        start = (page - 1) * size
        items = pending[start:start + size]
        return APIResponse(code=0, message='获取成功', data={'list': items, 'total': total})
    except Exception as e:
        logger.error(f"获取待审批列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'获取待审批列表失败: {str(e)}')


@router.get('/my', summary='获取我的审批')
async def get_my_approvals(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        all_approvals = _get_pending_approvals(db, current_user)
        total = len(all_approvals)
        start = (page - 1) * size
        items = all_approvals[start:start + size]
        return APIResponse(code=0, message='获取成功', data={'list': items, 'total': total})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取我的审批失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'获取我的审批失败: {str(e)}')


@router.get('/{approval_id}/history', summary='获取审批历史')
async def get_approval_history(
    approval_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取指定审批单的历史记录"""
    try:
        biz_type, biz_id = _parse_approval_id(approval_id)
        if biz_type == 'inbound':
            order = db.query(InboundOrder).filter(InboundOrder.id == biz_id).first()
            if not order:
                raise HTTPException(status_code=404, detail='入库单不存在')
            history = []
            if order.procurement_reviewed_at:
                is_approved = order.status not in ('rejected', 'cancelled')
                history.append({
                    'name': order.procurement_reviewer.real_name if order.procurement_reviewer else '',
                    'action': '审核通过' if is_approved else '审核驳回',
                    'comment': order.procurement_comment or '',
                    'timestamp': order.procurement_reviewed_at.isoformat(),
                    'type': 'success' if is_approved else 'danger',
                })
            # 如果审核通过且有越库领用，添加直领出库记录
            if order.outbound_order_id and order.status not in ('rejected', 'cancelled', 'pending_review'):
                outbound = order.outbound_order
                if outbound:
                    history.append({
                        'name': '系统自动',
                        'action': '生成越库领用出库单',
                        'comment': f'出库单号: {outbound.outbound_no}，数量: {float(outbound.quantity)}，状态: {outbound.status}',
                        'timestamp': outbound.created_at.isoformat() if outbound.created_at else '',
                        'type': 'primary',
                        'extra': {
                            'outbound_no': outbound.outbound_no,
                            'direct_issue_quantity': float(order.direct_issue_quantity) if order.direct_issue_quantity else 0,
                            'direct_issue_recipient': getattr(order, 'direct_issue_recipient', None),
                            'status': outbound.status,
                        }
                    })
            return APIResponse(code=0, message='获取成功', data=history)
        elif biz_type == 'purchase':
            order = db.query(PurchaseOrder).filter(PurchaseOrder.id == biz_id).first()
            if not order:
                raise HTTPException(status_code=404, detail='采购清单不存在')
            history = []
            if order.reviewed_at:
                is_approved = order.status not in ('rejected', 'cancelled')
                history.append({
                    'name': order.reviewer.real_name if order.reviewer else '',
                    'action': '审核通过' if is_approved else '审核驳回',
                    'comment': order.review_comment or '',
                    'timestamp': order.reviewed_at.isoformat(),
                    'type': 'success' if is_approved else 'danger',
                })
            return APIResponse(code=0, message='获取成功', data=history)
        else:
            return APIResponse(code=0, message='获取成功', data=[])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取审批历史失败: {str(e)}")
        return APIResponse(code=0, message='获取成功', data=[])


def _parse_approval_id(approval_id: str):
    """解析复合审批ID，返回 (业务类型, 业务ID)"""
    parts = approval_id.split('_', 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail=f'无效的审批ID: {approval_id}')
    return parts[0], int(parts[1])


class ApprovalActionRequest(BaseModel):
    action: str = Field('approve', description='审批动作: approve/reject')
    comment: str = Field('', description='审批意见')


@router.post('/{approval_id}/approve', summary='审批通过')
async def approval_approve(
    approval_id: str,
    request: ApprovalActionRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """审批通过（支持入/出/调/废/退等业务类型）"""
    try:
        biz_type, biz_id = _parse_approval_id(approval_id)
        action = request.action
        # reject 请求也可能通过此接口传入 action=reject
        logger.info(f"审批操作 | 用户: {current_user.username} | 类型: {biz_type} | ID: {biz_id} | 动作: {action}")

        if biz_type == 'inbound':
            from app.services.inbound_service import InboundService
            success, msg = InboundService.review_inbound_order(
                inbound_order_id=biz_id,
                review_type='receiving_review',
                action=action,
                reviewer_id=current_user.id,
                comment=request.comment,
                db=db
            )
            if not success:
                raise HTTPException(status_code=400, detail=msg)
            # 查询审核后的入库单，获取越库出库信息
            order = db.query(InboundOrder).filter(InboundOrder.id == biz_id).first()
            extra = {'status': action}
            if order and order.outbound_order_id and action == 'approve':
                outbound = order.outbound_order
                if outbound:
                    extra['outbound_order_no'] = outbound.outbound_no
                    extra['direct_issue_quantity'] = float(order.direct_issue_quantity) if order.direct_issue_quantity else 0
                    extra['inbound_status'] = order.status
            return APIResponse(code=0, message='操作成功', data=extra)
        elif biz_type == 'purchase':
            from app.services.purchase_service import PurchaseService as PurchaseSvc
            success, msg, _ = PurchaseSvc.approve_purchase(
                db=db,
                purchase_id=biz_id,
                reviewer_id=current_user.id,
                action=action,
                comment=request.comment,
            )
            if not success:
                raise HTTPException(status_code=400, detail=msg)
            return APIResponse(code=0, message='操作成功', data={})
        elif biz_type == 'transfer':
            from app.services.transfer_service import TransferService
            if action == 'approve':
                success, msg = TransferService.approve_transfer_order(biz_id, db)
            elif action == 'reject':
                # reject not implemented for transfer yet
                raise HTTPException(status_code=400, detail='调拨单暂不支持驳回')
            else:
                raise HTTPException(status_code=400, detail=f'无效的审批动作: {action}')
            if not success:
                raise HTTPException(status_code=400, detail=msg)
            return APIResponse(code=0, message=msg)
        elif biz_type == 'scrap':
            from app.services.scrap_service import ScrapService
            if action == 'approve':
                success, msg = ScrapService.approve_scrap_order(biz_id, db)
            elif action == 'reject':
                raise HTTPException(status_code=400, detail='报废单暂不支持驳回')
            else:
                raise HTTPException(status_code=400, detail=f'无效的审批动作: {action}')
            if not success:
                raise HTTPException(status_code=400, detail=msg)
            return APIResponse(code=0, message=msg)
        elif biz_type == 'return':
            from app.services.return_service import ReturnService
            if action == 'approve':
                success, msg = ReturnService.approve_return_order(biz_id, db)
            elif action == 'reject':
                raise HTTPException(status_code=400, detail='退货单暂不支持驳回')
            else:
                raise HTTPException(status_code=400, detail=f'无效的审批动作: {action}')
            if not success:
                raise HTTPException(status_code=400, detail=msg)
            return APIResponse(code=0, message=msg)
        else:
            raise HTTPException(status_code=400, detail=f'不支持的审批类型: {biz_type}')
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"审批操作失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'审批操作失败: {str(e)}')


@router.post('/{approval_id}/reject', summary='审批拒绝')
async def approval_reject(
    approval_id: str,
    request: ApprovalActionRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """审批拒绝"""
    # 复用 approve 逻辑，强制 action=reject
    request.action = 'reject'
    return await approval_approve(approval_id, request, db, current_user)
