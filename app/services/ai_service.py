"""
AI智能搜索服务
集成 DeepSeek API 实现物料同义词扩展和图片识别
（兼容 OpenAI API 格式）
"""
import base64
import io
from typing import List, Optional
from sqlalchemy.orm import Session

from app.config import AI_API_KEY, AI_API_URL, AI_MODEL, QWEN_API_KEY, QWEN_API_URL, QWEN_VL_MODEL
from app.utils.logger import logger


class AISearchService:
    """AI搜索服务，调用 DeepSeek API 进行语义扩展和图片识别"""

    @staticmethod
    def _call_deepseek(system_prompt: str, user_prompt: str, image_data: Optional[str] = None, max_tokens: int = 300, timeout: int = 30) -> Optional[str]:
        """调用 DeepSeek/OpenAI 兼容 API"""
        if not AI_API_KEY:
            logger.warning("AI_API_KEY 未配置，AI搜索不可用")
            return None

        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {AI_API_KEY}",
                "content-type": "application/json",
            }

            content = [{"type": "text", "text": user_prompt}]
            if image_data:
                content.insert(0, {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                })

            payload = {
                "model": AI_MODEL,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content if image_data else user_prompt},
                ],
            }

            with httpx.Client(timeout=timeout) as client:
                resp = client.post(AI_API_URL, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                return text

        except httpx.TimeoutException:
            logger.error("AI搜索超时")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"AI搜索HTTP错误: {e.response.status_code} {e.response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"AI搜索异常: {str(e)}")
            return None

    @staticmethod
    def expand_search_query(query: str) -> List[str]:
        """
        扩展搜索关键词，返回同义词和相关词列表
        例如: "螺丝刀" → ["螺丝刀", "起子", "改锥", "螺丝批"]
        """
        system_prompt = "你是矿山/矿区/工业仓储领域的物料管理专家。请根据用户输入的物料名称，列出矿山矿区仓库中常见的同义词、别称、俗称。优先使用矿山行业术语（如衬板、牙板、筛网、钢球、托辊、输送带、黄药、浮选剂、破碎机配件、球磨机、颚破等）。只返回逗号分隔的词列表，不要序号，不要其他任何文字。"

        user_prompt = f"请列出「{query}」的所有常见同义词和别称，包括原始词本身："

        result = AISearchService._call_deepseek(system_prompt, user_prompt)
        if not result:
            return [query]

        terms = [t.strip() for t in result.replace("，", ",").split(",") if t.strip()]
        if query not in terms:
            terms.insert(0, query)

        logger.info(f"AI扩展关键词: {query} → {terms}")
        return terms

    @staticmethod
    def identify_material_from_image(image_bytes: bytes) -> Optional[str]:
        """
        通过图片识别物料，返回识别的物料名称
        """
        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"图片编码失败: {str(e)}")
            return None

        system_prompt = "你是一个物料识别专家。请根据用户上传的图片，识别这是什么工具、零件或物料。只需要回复物料的标准中文名称，不要其他任何文字说明。"

        user_prompt = "请识别图中的物料，只回复标准中文名称："

        result = AISearchService._call_deepseek(system_prompt, user_prompt, image_data=image_b64)
        if not result:
            return None

        name = result.strip().strip('"').strip("'").strip("。")
        logger.info(f"AI图片识别结果: {name}")
        return name

    @staticmethod
    def identify_keywords_from_image(image_b64: str) -> Optional[List[str]]:
        """识别图片中的物料关键词。优先 Qwen-VL，否则用增强像素分析+DeepSeek推理。"""
        # Qwen-VL 优先
        if QWEN_API_KEY:
            try:
                import httpx
                h = {"Authorization": f"Bearer {QWEN_API_KEY}", "Content-Type": "application/json"}
                p = {"model": QWEN_VL_MODEL, "max_tokens": 100, "messages": [
                    {"role": "system", "content": "你是矿山/工业仓储物料识别专家。只回复5个最可能的中文物料名称关键词，逗号分隔。"},
                    {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}, {"type": "text", "text": "这是什么物料？5个关键词："}]}
                ]}
                r = httpx.post(QWEN_API_URL, headers=h, json=p, timeout=30)
                r.raise_for_status()
                txt = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if txt:
                    kw = [k.strip() for k in txt.replace("\n",",").replace("，",",").split(",") if k.strip()][:5]
                    if kw: logger.info(f"Qwen-VL: {kw}"); return kw
            except Exception as e:
                logger.warning(f"Qwen-VL 不可用: {str(e)[:80]}")
        # 回退：增强像素分析
        return AISearchService._infer_keywords_from_pixels(image_b64)

    @staticmethod
    def _infer_keywords_from_pixels(image_b64: str) -> Optional[List[str]]:
        """增强像素分析：多分辨率特征提取 + DeepSeek推理"""
        try:
            from PIL import Image

            img_bytes = base64.b64decode(image_b64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            w, h = img.size

            def analyze_grid(img_obj, grid_size):
                """分析指定网格大小的颜色/纹理特征"""
                sw, sh = grid_size, grid_size
                img_s = img_obj.resize((sw, sh))
                px = list(img_s.getdata())
                hist = {}
                for r, g, b in px:
                    bkt = f"{r//16*16},{g//16*16},{b//16*16}"
                    hist[bkt] = hist.get(bkt, 0) + 1
                top = sorted(hist.items(), key=lambda x: -x[1])[:8]
                total = sw * sh
                descs = []
                for k, c in top:
                    parts = k.split(",")
                    hx = f"#{int(parts[0]):02x}{int(parts[1]):02x}{int(parts[2]):02x}"
                    descs.append(f"{hx}({c*100//total}%)")
                return ";".join(descs)

            coarse = analyze_grid(img, 32)
            fine = analyze_grid(img, 128)

            aspect = w / h
            shape = "横长" if aspect > 1.5 else "竖长" if aspect < 0.7 else "正方形" if 0.9<aspect<1.1 else "略宽" if aspect>1.1 else "略高"

            features = f"粗色:{coarse}\n细色:{fine}\n形状:{shape} 尺寸:{w}x{h}"

            result = AISearchService._call_deepseek(
                "你是矿山/工业仓储领域的物料识别专家。根据图片的多尺度颜色特征数据（粗分辨率+细分辨率），结合尺寸和形状信息，推理这是什么工具、零件、耗材或物料。只回复5个最可能的中文物料名称关键词，逗号分隔，不要序号。",
                f"图片特征：\n{features}\n\n推理这是什么物料？5个关键词：",
                max_tokens=100
            )
            if not result:
                return None
            kw = [k.strip() for k in result.replace("\n",",").replace("，",",").split(",") if k.strip()][:5]
            logger.info(f"像素推理: {features[:80]}... → {kw}")
            return kw if kw else None
        except ImportError:
            logger.warning("Pillow 未安装")
            return None
        except Exception as e:
            logger.error(f"像素推理异常: {str(e)}")
            return None

    @staticmethod
    def cache_aliases(material_id: int, alias: str, db: Session):
        """缓存同义词到数据库，避免重复查询"""
        from app.models.catalog import MaterialAlias
        existing = db.query(MaterialAlias).filter(
            MaterialAlias.material_id == material_id,
            MaterialAlias.alias == alias
        ).first()
        if not existing:
            db.add(MaterialAlias(material_id=material_id, alias=alias))
            db.commit()


class AIPredictionService:
    """AI消耗预测服务，基于历史消耗数据预测未来消耗量"""

    @staticmethod
    def predict_consumption(prediction_input: dict, days: int) -> dict:
        """
        调用 DeepSeek 进行消耗预测，失败时回退到统计方法。

        返回结构：
        {
            "predictions": [{"material_id", "material_code", "material_name",
                             "specification", "unit", "current_qty", "previous_qty",
                             "predicted_qty", "confidence", "trend", "analysis"}],
            "summary": {"total_predicted", "overall_trend", "insights"},
            "ai_generated": bool
        }
        """
        if not AI_API_KEY:
            logger.warning("AI_API_KEY 未配置，使用统计回退")
            return AIPredictionService._fallback_prediction(prediction_input, days)

        try:
            system_prompt = """你是一个仓储物料消耗预测专家。根据历史消耗数据，预测未来一段时间的消耗量。

分析以下维度：
1. 趋势：消耗量是上升、下降还是持平
2. 周期性：是否存在明显的月度/周度周期
3. 异常：是否存在需要修正的异常峰值

对每个物料，输出：
- material_id: 物料ID（从输入中获取，必须原样返回）
- material_name: 物料名称
- predicted_qty: 预测消耗量（数字，保留1位小数）
- confidence: 置信度 high/medium/low（基于数据波动性和样本量）
- trend: 趋势方向 up/down/stable
- analysis: 简短分析（15字以内）

必须输出纯 JSON，不要 markdown 格式：
{"predictions":[],"summary":{"total_predicted":0,"overall_trend":"up","insights":""}}"""

            items = prediction_input.get('items', [])
            item_lines = []
            for item in items:
                weekly = item.get('weekly_data', [])
                weekly_str = ', '.join([f"第{w['week_index']}周={w['consumption']}" for w in weekly])
                item_lines.append(
                    f"ID={item.get('material_id')} | {item.get('material_name','?')} | {item.get('specification','-')} | "
                    f"{item.get('unit','-')} | "
                    f"当前={item.get('current_qty',0)} | 上期={item.get('previous_qty',0)} | "
                    f"变化={item.get('change_pct',0)}% | 周明细: {weekly_str}"
                )

            cp = prediction_input.get('current_period', {})
            pp = prediction_input.get('previous_period', {})
            change_pct = prediction_input.get('consumption_change_pct', 0)

            user_prompt = (
                f"请基于以下 {days} 天的历史数据，预测未来 {days} 天的物料消耗。\n\n"
                f"=== 周期概览 ===\n"
                f"当前周期（最近 {days} 天）：{cp.get('start','')[:10]} ~ {cp.get('end','')[:10]}\n"
                f"对比周期（前 {days} 天）：{pp.get('start','')[:10]} ~ {pp.get('end','')[:10]}\n"
                f"总消耗对比：当前 {cp.get('total_consumption',0)}，上期 {pp.get('total_consumption',0)}，变化 {change_pct}%\n\n"
                f"=== Top {len(item_lines)} 物料详情 ===\n" + "\n".join(item_lines) + "\n\n请输出 JSON 预测结果。"
            )

            logger.info(f"AI消耗预测请求: days={days}, items={len(items)}")
            result = AISearchService._call_deepseek(
                system_prompt, user_prompt,
                max_tokens=2000, timeout=60
            )

            if not result:
                logger.warning("AI预测返回空，使用统计回退")
                return AIPredictionService._fallback_prediction(prediction_input, days)

            parsed = AIPredictionService._parse_prediction_response(result, items)
            if parsed:
                parsed['ai_generated'] = True
                logger.info(f"AI预测成功: {len(parsed.get('predictions',[]))} 条物料")
                return parsed

            logger.warning("AI预测JSON解析失败，使用统计回退")
            return AIPredictionService._fallback_prediction(prediction_input, days)

        except Exception as e:
            logger.error(f"AI预测异常: {str(e)}，使用统计回退")
            return AIPredictionService._fallback_prediction(prediction_input, days)

    @staticmethod
    def _parse_prediction_response(text: str, fallback_items: list) -> Optional[dict]:
        """解析 AI 返回的 JSON，失败返回 None"""
        import re, json

        # 尝试直接解析
        text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取
            m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if m:
                try:
                    data = json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    return None
            else:
                return None

        if not isinstance(data, dict):
            return None

        predictions = data.get('predictions', [])
        if not isinstance(predictions, list):
            return None

        # 验证并补充每个预测，支持按 material_id 或 material_name 匹配
        item_map = {i.get('material_id'): i for i in fallback_items}
        name_map = {}
        for i in fallback_items:
            if i.get('material_name'):
                name_map[i['material_name'].strip().lower()] = i

        validated = []
        for p in predictions:
            mid = p.get('material_id')
            fi = item_map.get(mid)
            # 如果没有 material_id，尝试按名称匹配
            if fi is None and p.get('material_name'):
                fi = name_map.get(p['material_name'].strip().lower())
            if fi is None:
                continue
            validated.append({
                'material_id': mid,
                'material_code': fi.get('material_code') if fi else p.get('material_code'),
                'material_name': fi.get('material_name') if fi else p.get('material_name'),
                'specification': fi.get('specification') if fi else p.get('specification'),
                'unit': fi.get('unit') if fi else p.get('unit'),
                'current_qty': float(fi.get('current_qty', 0)) if fi else 0,
                'previous_qty': float(fi.get('previous_qty', 0)) if fi else 0,
                'predicted_qty': float(p.get('predicted_qty', 0)),
                'confidence': str(p.get('confidence', 'medium')),
                'trend': str(p.get('trend', 'stable')),
                'analysis': str(p.get('analysis', '')),
            })

        summary = data.get('summary', {})
        if not isinstance(summary, dict):
            summary = {}

        return {
            'predictions': validated,
            'summary': {
                'total_predicted': float(summary.get('total_predicted', sum(p['predicted_qty'] for p in validated))),
                'overall_trend': str(summary.get('overall_trend', 'stable')),
                'insights': str(summary.get('insights', '')),
            },
        }

    @staticmethod
    def _fallback_prediction(prediction_input: dict, days: int) -> dict:
        """统计回退：基于增长率外推预测"""
        items = prediction_input.get('items', [])
        predictions = []
        total_predicted = 0.0

        for item in items:
            cur = float(item.get('current_qty', 0))
            prev = float(item.get('previous_qty', 0))
            change_pct = float(item.get('change_pct', 0))

            # 预测 = 当前 * (当前/上期) 增长率
            if prev > 0:
                rate = cur / prev
            else:
                rate = 1.1
            predicted = round(cur * rate, 1)

            # 置信度
            abs_change = abs(change_pct)
            if abs_change < 5:
                confidence = 'high'
            elif abs_change < 20:
                confidence = 'medium'
            else:
                confidence = 'low'

            # 趋势
            if change_pct > 10:
                trend = 'up'
            elif change_pct < -10:
                trend = 'down'
            else:
                trend = 'stable'

            analysis = f"{'上升' if trend=='up' else '下降' if trend=='down' else '持平'}趋势"

            predictions.append({
                'material_id': item.get('material_id'),
                'material_code': item.get('material_code'),
                'material_name': item.get('material_name'),
                'specification': item.get('specification'),
                'unit': item.get('unit'),
                'current_qty': cur,
                'previous_qty': prev,
                'predicted_qty': predicted,
                'confidence': confidence,
                'trend': trend,
                'analysis': analysis,
            })
            total_predicted += predicted

        return {
            'predictions': predictions,
            'summary': {
                'total_predicted': round(total_predicted, 1),
                'overall_trend': 'stable',
                'insights': '基于统计方法的回退预测（AI不可用）',
            },
            'ai_generated': False,
        }
