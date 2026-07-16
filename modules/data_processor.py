"""
财务数据处理器 - 多表存储、数据清洗、摘要统计、单元格编辑
"""
from __future__ import annotations

import os
import json
import hashlib
from collections import OrderedDict
from datetime import datetime
from typing import Any

from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls', 'xlsm', 'xltx', 'xltm'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# 进程内多表存储（重启后清空；持久化依赖 database.history_records）
# 结构: {table_id: {df, filename, file_hash, summary, preview_data, preview_columns}}
_tables: OrderedDict[str, dict] = OrderedDict()
_active_table_id: str | None = None  # 当前正在操作的表
_counter = 0


def _next_id() -> str:
    global _counter
    _counter += 1
    return f't{_counter}'


def allowed_file(filename: str) -> bool:
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return ext in ALLOWED_EXTENSIONS


def allowed_image(filename: str) -> bool:
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return ext in IMAGE_EXTENSIONS


def get_file_hash(filepath: str) -> str:
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_file(filepath: str, filename: str) -> pd.DataFrame:
    """根据扩展名加载 CSV 或 Excel 文件"""
    ext = ''
    if '.' in filepath:
        ext = filepath.rsplit('.', 1)[1].lower()
    if not ext and '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
    if not ext:
        ext = 'csv'

    if ext == 'csv':
        for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']:
            try:
                df = pd.read_csv(filepath, encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            df = pd.read_csv(filepath, encoding='utf-8', errors='replace')
    elif ext in ('xlsx', 'xlsm', 'xltx', 'xltm'):
        df = pd.read_excel(filepath, engine='openpyxl')
    elif ext == 'xls':
        try:
            df = pd.read_excel(filepath, engine='xlrd')
        except Exception:
            df = pd.read_excel(filepath, engine='openpyxl')
    else:
        for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']:
            try:
                df = pd.read_csv(filepath, encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise ValueError(f'不支持的文件格式: {ext}')
    return df


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how='all').dropna(axis=1, how='all')
    if len(df.columns) == 0:
        return df

    # 去重列名，避免 KeyError
    cols = [str(c).strip() for c in df.columns]
    seen: dict[str, int] = {}
    new_cols = []
    for c in cols:
        key = c if c else '列'
        if key in seen:
            seen[key] += 1
            new_cols.append(f'{key}_{seen[key]}')
        else:
            seen[key] = 0
            new_cols.append(key)
    df.columns = new_cols

    for i in range(len(df.columns)):
        col = df.columns[i]
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            # 先尝试转为数值，保留数值列的 dtype 以便后续检测
            numeric_vals = pd.to_numeric(df[col], errors='coerce')
            if numeric_vals.notna().sum() / max(len(df[col]), 1) > 0.7:
                df[col] = numeric_vals
            else:
                df.iloc[:, i] = df.iloc[:, i].fillna('').astype(str).str.strip()
    # 保证行号与编辑器位置索引一致（iloc / 前端 row 对齐）
    return df.reset_index(drop=True)


def detect_column_types(df: pd.DataFrame) -> dict:
    col_types = {}
    for col in df.columns:
        col_lower = col.lower()
        sample = df[col].dropna()
        if len(sample) == 0:
            col_types[col] = 'unknown'
            continue

        # 关键字匹配（扩展中文财务术语）
        if any(kw in col_lower for kw in
               ['金额', 'amount', '元', 'money', 'value', '总额', '余额', 'balance',
                '账款', '应收', '应付', '收入', '成本', '利润', '资产', '负债', '权益',
                '净值', '现金流', '净利', '毛利', '费用', '支出', '销售', '营业', '税款',
                '税额', '工资', '薪酬', '折旧', '摊销', '存货', '借款', '投资', '融资',
                '汇率', '利率', '单价', '数量', '合计', '总计', '小计', '净额', '含税',
                '不含税', '逾期', '坏账', '预收', '预付', '押金', '保证金', '实收', '实付']):
            col_types[col] = 'amount'
        elif any(kw in col_lower for kw in
                 ['日期', 'date', '时间', 'time', '年月日', '年月', '年', '月', '日',
                  '季度', '年度', '财年', '期间', 'period']):
            col_types[col] = 'date'
        elif any(kw in col_lower for kw in
                 ['凭证', 'voucher', '发票', 'invoice', '单据', '编号', '号码',
                  'no', 'id', '序号', '代码', 'code', '编号', '单号', '流水号',
                  '合同号', '档案号', '账套']):
            col_types[col] = 'voucher_id'
        elif any(kw in col_lower for kw in
                 ['类别', '分类', 'category', 'type', '类型', '科目', 'account',
                  '部门', 'dept', 'department', '摘要', 'description', '备注', 'remark',
                  '用途', '名称', 'name', '公司', '单位', '客户', '供应商', '项目',
                  '产品', '品牌', '区域', '地区', '状态', 'status', '说明', '明细']):
            col_types[col] = 'category'
        elif pd.api.types.is_numeric_dtype(sample):
            col_types[col] = 'amount'
        elif pd.api.types.is_datetime64_any_dtype(sample):
            col_types[col] = 'date'
        else:
            # 最终回退：尝试将字符串列转为数值，若大部分可转则判定为金额列
            try:
                numeric_sample = pd.to_numeric(sample, errors='coerce')
                if len(numeric_sample.dropna()) / len(sample) > 0.7:
                    col_types[col] = 'amount'
                else:
                    col_types[col] = 'category'
            except Exception:
                col_types[col] = 'category'

    return col_types


def get_amount_column(df: pd.DataFrame) -> str | None:
    col_types = detect_column_types(df)
    for col, ctype in col_types.items():
        if ctype == 'amount':
            return col
    return None


def get_date_column(df: pd.DataFrame) -> str | None:
    col_types = detect_column_types(df)
    for col, ctype in col_types.items():
        if ctype == 'date':
            return col
    return None


def generate_summary(df: pd.DataFrame) -> dict:
    col_types = detect_column_types(df)
    amount_col = get_amount_column(df)
    date_col = get_date_column(df)

    summary = {
        'total_rows': len(df),
        'total_columns': len(df.columns),
        'columns': list(df.columns),
        'column_types': col_types,
        'missing_values': df.isnull().sum().to_dict(),
        'duplicate_rows': int(df.duplicated().sum()),
    }

    if amount_col:
        amt = pd.to_numeric(df[amount_col], errors='coerce')
        summary['amount_stats'] = {
            'column': amount_col,
            'total': float(amt.sum()),
            'mean': float(amt.mean()),
            'median': float(amt.median()),
            'std': float(amt.std()),
            'min': float(amt.min()),
            'max': float(amt.max()),
            'positive_count': int((amt > 0).sum()),
            'negative_count': int((amt < 0).sum()),
            'zero_count': int((amt == 0).sum()),
        }

    if date_col:
        try:
            dates = pd.to_datetime(df[date_col], errors='coerce')
            valid_dates = dates.dropna()
            if len(valid_dates) > 0:
                summary['date_range'] = {
                    'column': date_col,
                    'start': valid_dates.min().strftime('%Y-%m-%d'),
                    'end': valid_dates.max().strftime('%Y-%m-%d'),
                    'days_span': (valid_dates.max() - valid_dates.min()).days,
                }
        except Exception:
            pass

    cat_cols = [c for c, t in col_types.items() if t == 'category']
    summary['category_counts'] = {}
    for col in cat_cols[:5]:
        vc = df[col].value_counts().head(20)
        summary['category_counts'][col] = {str(k): int(v) for k, v in vc.items()}

    return summary


# ============================================================
# 多表管理
# ============================================================

def get_tables() -> list[dict]:
    """返回所有已加载表的摘要列表"""
    return [
        {
            'id': tid,
            'filename': t['filename'],
            'rows': len(t['df']),
            'columns': len(t['df'].columns),
            'column_names': list(t['df'].columns),
        }
        for tid, t in _tables.items()
    ]


def get_table(table_id: str) -> dict | None:
    return _tables.get(table_id)


def get_active_table() -> dict | None:
    global _active_table_id
    if _active_table_id and _active_table_id in _tables:
        return _tables[_active_table_id]
    # 如果还没设置活动表，自动选第一个
    if _tables:
        _active_table_id = next(iter(_tables.keys()))
        return _tables[_active_table_id]
    return None


def set_active_table(table_id: str) -> bool:
    global _active_table_id
    if table_id in _tables:
        _active_table_id = table_id
        return True
    return False


def get_active_table_id() -> str | None:
    return _active_table_id


# ============================================================
# 上传处理
# ============================================================

def _save_file(file) -> tuple[str, str, str]:
    """保存上传文件，返回 (filepath, original_filename, table_id)"""
    original_filename = file.filename or 'unknown.csv'
    safe_name = secure_filename(original_filename)
    orig_ext = (original_filename.rsplit('.', 1)[1].lower()
                if '.' in original_filename else 'csv')

    if not safe_name or safe_name == '':
        safe_name = f'uploaded_{datetime.now().strftime("%Y%m%d_%H%M%S")}.{orig_ext}'
    elif safe_name.lstrip('.') == orig_ext and '.' not in safe_name.rstrip(orig_ext):
        safe_name = f'uploaded_{datetime.now().strftime("%Y%m%d_%H%M%S")}.{orig_ext}'

    filepath = os.path.join(UPLOAD_FOLDER, safe_name)
    file.save(filepath)
    return filepath, original_filename


def process_upload(file) -> dict:
    """处理单文件上传，返回结果（不自动建表，由调用方决定）"""
    if not file or file.filename == '':
        return {'success': False, 'error': '未选择文件'}

    original_filename = file.filename

    if not allowed_file(original_filename):
        return {'success': False, 'error': '不支持的文件格式，请上传 CSV 或 Excel 文件'}

    filepath, original_filename = _save_file(file)

    try:
        df = load_file(filepath, original_filename)
        df = clean_data(df)

        if len(df) == 0:
            return {'success': False, 'error': '文件为空或无法解析'}

        table_id = _next_id()
        summary = generate_summary(df)

        _tables[table_id] = {
            'df': df,
            'filename': original_filename,
            'file_hash': get_file_hash(filepath),
            'summary': summary,
            'preview_data': df.head(100).fillna('').to_dict(orient='records'),
            'preview_columns': list(df.columns),
        }

        # 第一个表自动设为活动表
        global _active_table_id
        if _active_table_id is None:
            _active_table_id = table_id

        return {
            'success': True,
            'table_id': table_id,
            'filename': original_filename,
            'summary': summary,
            'preview_data': _tables[table_id]['preview_data'],
            'preview_columns': _tables[table_id]['preview_columns'],
        }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        return {'success': False, 'error': f'文件处理失败: {str(e)}', 'traceback': tb}


def process_image_upload(file) -> dict:
    """处理图片上传并 OCR 识别"""
    if not file or file.filename == '':
        return {'success': False, 'error': '未选择图片'}

    original_filename = file.filename
    if not allowed_image(original_filename):
        return {'success': False, 'error': f'不支持的图片格式，支持: {", ".join(IMAGE_EXTENSIONS)}'}

    filepath, original_filename = _save_file(file)

    try:
        extracted_data = _ocr_image(filepath)
        if not extracted_data:
            return {'success': False, 'error': '未能从图片中识别到表格数据，请确保图片包含清晰的表格或CSV文本'}

        df = _dataframe_from_ocr_rows(extracted_data)
        if df.empty:
            return {'success': False, 'error': '未能从图片中提取有效数据'}

        table_id = _next_id()
        summary = generate_summary(df)

        _tables[table_id] = {
            'df': df,
            'filename': f'[图片识别] {original_filename}',
            'file_hash': get_file_hash(filepath),
            'summary': summary,
            'preview_data': df.head(100).fillna('').to_dict(orient='records'),
            'preview_columns': list(df.columns),
        }

        global _active_table_id
        if _active_table_id is None:
            _active_table_id = table_id

        return {
            'success': True,
            'table_id': table_id,
            'filename': _tables[table_id]['filename'],
            'summary': summary,
            'preview_data': _tables[table_id]['preview_data'],
            'preview_columns': _tables[table_id]['preview_columns'],
        }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        return {'success': False, 'error': f'图片识别失败: {str(e)}', 'traceback': tb}


def _preprocess_image_for_ocr(img):
    """预处理截图：反色、放大、增强对比度（适配深色编辑器截图）"""
    from PIL import Image, ImageOps, ImageEnhance

    gray = img.convert('L') if img.mode != 'L' else img
    arr = np.array(gray)
    if arr.mean() < 128:
        gray = ImageOps.invert(gray)

    w, h = gray.size
    if w < 1400:
        scale = 1400 / w
        gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    gray = ImageEnhance.Sharpness(gray).enhance(1.5)
    return gray


def _parse_ocr_csv_text(text: str) -> list[list[str]]:
    """从 OCR 文本解析 CSV 行（适配代码编辑器截图）"""
    import csv
    import io
    import re

    table = []
    for raw_line in text.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r'^\d+\s*', '', line)
        line = line.replace('，', ',').replace('；', ',')
        if ',' not in line:
            continue
        try:
            row = next(csv.reader(io.StringIO(line)))
            row = [c.strip() for c in row if c is not None]
            if row and any(c for c in row):
                table.append(row)
        except Exception:
            parts = [c.strip() for c in line.split(',') if c.strip()]
            if parts:
                table.append(parts)
    return table


def _parse_text_to_table(text: str) -> list[list[str]]:
    """将 OCR 纯文本解析为表格行"""
    import re

    csv_rows = _parse_ocr_csv_text(text)
    if len(csv_rows) >= 2:
        return csv_rows

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    table = []
    for line in lines:
        line = re.sub(r'^\d+\s*', '', line)
        if '\t' in line:
            table.append([c.strip() for c in line.split('\t') if c.strip()])
        elif '|' in line:
            table.append([c.strip() for c in line.split('|') if c.strip()])
        elif ',' in line:
            table.append([c.strip() for c in line.split(',') if c.strip()])
        else:
            cells = re.split(r'\s{2,}', line)
            if len(cells) <= 1:
                cells = line.split()
            if cells:
                table.append([c.strip() for c in cells if c.strip()])
    return table


def _ocr_by_coordinates(img) -> list[list[str]]:
    """按坐标分组识别表格"""
    import pytesseract

    data = None
    for lang in ('chi_sim+eng', 'chi_sim', 'eng'):
        try:
            data = pytesseract.image_to_data(
                img, lang=lang, output_type=pytesseract.Output.DICT)
            break
        except Exception:
            continue
    if not data:
        return []

    words = []
    for i, text in enumerate(data['text']):
        text = (text or '').strip()
        if not text:
            continue
        try:
            conf = int(float(data['conf'][i]))
        except (ValueError, TypeError):
            conf = -1
        if 0 <= conf < 25:
            continue
        y = data['top'][i] + data['height'][i] / 2
        x = data['left'][i]
        words.append((y, x, text))

    if not words:
        return []

    rows = OrderedDict()
    for y, x, text in words:
        row_key = round(y / 18) * 18
        rows.setdefault(row_key, []).append((x, text))

    table = []
    for _, cells in sorted(rows.items()):
        cells.sort(key=lambda c: c[0])
        table.append([c[1] for c in cells])
    return table


def _ocr_image(filepath: str) -> list[list[str]]:
    """OCR 识别图片中的表格（CSV截图优先整行识别）"""
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(filepath)
        processed = _preprocess_image_for_ocr(img)

        ocr_config = '--psm 6 -c preserve_interword_spaces=1'
        for lang in ('chi_sim+eng', 'chi_sim', 'eng'):
            try:
                text = pytesseract.image_to_string(processed, lang=lang, config=ocr_config)
                csv_table = _parse_ocr_csv_text(text)
                if len(csv_table) >= 2:
                    return csv_table
            except Exception:
                continue

        coord_table = _ocr_by_coordinates(processed)
        if len(coord_table) >= 2:
            return coord_table

        text = pytesseract.image_to_string(processed, lang='chi_sim+eng')
        return _parse_text_to_table(text)
    except ImportError:
        pass
    except Exception as e:
        print(f'pytesseract OCR error: {e}', flush=True)

    try:
        import easyocr
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
        results = reader.readtext(filepath)
        if not results:
            return []

        rows = OrderedDict()
        for (bbox, text, conf) in results:
            if conf < 0.3:
                continue
            y_center = (bbox[0][1] + bbox[2][1]) / 2
            row_key = round(y_center / 20) * 20
            rows.setdefault(row_key, []).append((bbox[0][0], text.strip()))

        table = []
        for _, cells in sorted(rows.items()):
            cells.sort(key=lambda x: x[0])
            table.append([c[1] for c in cells])
        return table
    except ImportError:
        pass
    except Exception as e:
        print(f'easyocr error: {e}', flush=True)

    return []


def _normalize_headers(headers: list) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for h in headers:
        key = str(h).strip() if str(h).strip() else '列'
        if key in seen:
            seen[key] += 1
            result.append(f'{key}_{seen[key]}')
        else:
            seen[key] = 0
            result.append(key)
    return result


def _dataframe_from_ocr_rows(extracted_data: list[list[str]]) -> pd.DataFrame:
    """将 OCR 行数据转为 DataFrame"""
    valid_rows = [r for r in extracted_data if r and any(str(c).strip() for c in r)]
    if len(valid_rows) < 2:
        raise ValueError('识别到的数据行数不足，请上传更清晰的图片')

    headers = _normalize_headers([str(c).strip() for c in valid_rows[0]])
    data_rows = []
    for row in valid_rows[1:]:
        cells = [str(c).strip() for c in row]
        while len(cells) < len(headers):
            cells.append('')
        data_rows.append(cells[:len(headers)])

    df = pd.DataFrame(data_rows, columns=headers)
    return clean_data(df)


def import_table_data(headers: list, rows: list[list]) -> dict:
    """从 OCR/AI 识别的表头与行数据创建表"""
    if not headers:
        return {'success': False, 'error': '表头为空'}

    max_cols = len(headers)
    normalized_rows = []
    for row in rows:
        cells = list(row)[:max_cols]
        while len(cells) < max_cols:
            cells.append('')
        normalized_rows.append(cells)

    df = pd.DataFrame(normalized_rows, columns=headers)
    df = clean_data(df)
    if len(df) == 0:
        return {'success': False, 'error': '未能从识别结果中提取有效数据'}

    table_id = _next_id()
    summary = generate_summary(df)
    _tables[table_id] = {
        'df': df,
        'filename': '[识图导入] 表格数据',
        'file_hash': '',
        'summary': summary,
        'preview_data': df.head(100).fillna('').to_dict(orient='records'),
        'preview_columns': list(df.columns),
    }

    global _active_table_id
    if _active_table_id is None:
        _active_table_id = table_id

    return {
        'success': True,
        'table_id': table_id,
        'filename': _tables[table_id]['filename'],
        'summary': summary,
        'preview_data': _tables[table_id]['preview_data'],
        'preview_columns': _tables[table_id]['preview_columns'],
    }


# ============================================================
# 单元格编辑
# ============================================================

def get_table_data(table_id: str, page: int = 1, per_page: int = 50) -> dict:
    """获取表数据（分页）"""
    t = _tables.get(table_id)
    if not t:
        return {'success': False, 'error': '表不存在'}
    df = t['df']
    total = len(df)
    start = (page - 1) * per_page
    end = start + per_page
    page_df = df.iloc[start:end]
    return {
        'success': True,
        'table_id': table_id,
        'filename': t['filename'],
        'columns': list(df.columns),
        'column_types': detect_column_types(df),
        'rows': page_df.fillna('').to_dict(orient='records'),
        'total_rows': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
    }


def update_cell(table_id: str, row_idx: int, column: str, value: Any) -> dict:
    """更新单元格（按位置索引，与编辑器行号一致）"""
    t = _tables.get(table_id)
    if not t:
        return {'success': False, 'error': '表不存在'}
    df = t['df']
    try:
        if row_idx < 0 or row_idx >= len(df):
            return {'success': False, 'error': f'行索引越界: {row_idx}'}
        if column not in df.columns:
            return {'success': False, 'error': f'列不存在: {column}'}
        # 编辑器传入的是位置下标，必须用 iloc，不能用 label 的 at
        col_pos = df.columns.get_loc(column)
        if isinstance(col_pos, (slice, list)) or hasattr(col_pos, '__iter__') and not isinstance(col_pos, (str, int)):
            col_pos = int(list(col_pos)[0]) if not isinstance(col_pos, int) else col_pos
        # 允许写入任意文本，避免数值列赋值失败
        if df.dtypes.iloc[col_pos] != object:
            df[column] = df[column].astype(object)
            col_pos = df.columns.get_loc(column)
        df.iloc[row_idx, col_pos] = value
        t['df'] = df
        t['summary'] = generate_summary(df)
        t['preview_data'] = df.head(100).fillna('').to_dict(orient='records')
        t['preview_columns'] = list(df.columns)
        t['dirty'] = True
        return {'success': True}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def add_row(table_id: str, row_data: dict = None) -> dict:
    """添加一行"""
    t = _tables.get(table_id)
    if not t:
        return {'success': False, 'error': '表不存在'}
    df = t['df']
    new_row = row_data or {}
    # 填充缺失列
    for col in df.columns:
        if col not in new_row:
            new_row[col] = ''
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    t['df'] = df
    t['summary'] = generate_summary(df)
    t['preview_data'] = df.head(100).fillna('').to_dict(orient='records')
    return {'success': True, 'new_index': len(df) - 1}


def delete_row(table_id: str, row_idx: int) -> dict:
    """删除一行"""
    t = _tables.get(table_id)
    if not t:
        return {'success': False, 'error': '表不存在'}
    df = t['df']
    if row_idx < 0 or row_idx >= len(df):
        return {'success': False, 'error': '行索引越界'}
    df = df.drop(df.index[row_idx]).reset_index(drop=True)
    t['df'] = df
    t['summary'] = generate_summary(df)
    t['preview_data'] = df.head(100).fillna('').to_dict(orient='records')
    return {'success': True}


def add_column(table_id: str, col_name: str, default_value: Any = '') -> dict:
    """添加一列"""
    t = _tables.get(table_id)
    if not t:
        return {'success': False, 'error': '表不存在'}
    if col_name in t['df'].columns:
        return {'success': False, 'error': f'列 "{col_name}" 已存在'}
    t['df'][col_name] = default_value
    t['summary'] = generate_summary(t['df'])
    t['preview_data'] = t['df'].head(100).fillna('').to_dict(orient='records')
    t['preview_columns'] = list(t['df'].columns)
    return {'success': True}


def delete_column(table_id: str, col_name: str) -> dict:
    """删除一列"""
    t = _tables.get(table_id)
    if not t:
        return {'success': False, 'error': '表不存在'}
    if col_name not in t['df'].columns:
        return {'success': False, 'error': f'列 "{col_name}" 不存在'}
    t['df'] = t['df'].drop(columns=[col_name])
    t['summary'] = generate_summary(t['df'])
    t['preview_data'] = t['df'].head(100).fillna('').to_dict(orient='records')
    t['preview_columns'] = list(t['df'].columns)
    return {'success': True}


def delete_table(table_id: str) -> dict:
    """删除表"""
    global _active_table_id
    if table_id not in _tables:
        return {'success': False, 'error': '表不存在'}
    del _tables[table_id]
    if _active_table_id == table_id:
        _active_table_id = next(iter(_tables.keys())) if _tables else None
    return {'success': True}


def restore_table_from_df(df: pd.DataFrame, filename: str) -> str:
    """从历史记录恢复表到内存"""
    global _active_table_id
    df = clean_data(df.copy())
    table_id = _next_id()
    summary = generate_summary(df)
    _tables[table_id] = {
        'df': df,
        'filename': filename,
        'file_hash': '',
        'summary': summary,
        'preview_data': df.head(100).fillna('').to_dict(orient='records'),
        'preview_columns': list(df.columns),
    }
    _active_table_id = table_id
    return table_id


def clear_all_tables() -> None:
    """清空所有内存中的表数据（切换用户时调用）"""
    global _tables, _active_table_id, _counter
    _tables.clear()
    _active_table_id = None
    _counter = 0


def export_table_snapshot(table_id: str) -> dict | None:
    """导出整张表为可共享的 JSON 快照"""
    t = _tables.get(table_id)
    if not t:
        return None
    df = t['df']
    return {
        'columns': list(df.columns),
        'rows': df.fillna('').to_dict(orient='records'),
        'filename': t['filename'],
    }


def persist_table(table_id: str, user_id: int | None) -> None:
    """把内存表写入 SQLite，并同步关联的历史记录。"""
    if not user_id or not table_id:
        return
    t = _tables.get(table_id)
    if not t:
        return
    try:
        from modules.database import upsert_working_table, update_history_table_data
        upsert_working_table(user_id, table_id, t.get('filename', ''), t['df'])
        hid = t.get('history_id')
        if hid:
            update_history_table_data(int(hid), t['df'], user_id)
    except Exception as exc:
        print(f'[persist_table] {exc}', flush=True)


def restore_working_tables_for_user(user_id: int, force: bool = False) -> int:
    """从 SQLite 恢复当前用户的工作表到内存。

    force=True：用数据库覆盖同 table_key 的内存表（协同写回后必须开启，
    否则非空内存会一直展示旧数据）。
    """
    global _active_table_id
    if not user_id:
        return 0
    if _tables and not force:
        return 0
    try:
        from modules.database import list_working_tables, load_working_table
        items = list_working_tables(user_id)
    except Exception:
        return 0
    restored = 0
    for item in items:
        key = item['table_key']
        packed = load_working_table(user_id, key)
        if not packed:
            continue
        df = clean_data(packed['df'])
        summary = generate_summary(df)
        _tables[key] = {
            'df': df,
            'filename': packed.get('filename') or item.get('filename') or '未命名',
            'file_hash': '',
            'summary': summary,
            'preview_data': df.head(100).fillna('').to_dict(orient='records'),
            'preview_columns': list(df.columns),
            'history_id': (_tables.get(key) or {}).get('history_id'),
        }
        if _active_table_id is None or force:
            # force 时优先最新更新的表（list 已按 updated_at DESC）
            if restored == 0:
                _active_table_id = key
        restored += 1
    return restored


def bind_table_history(table_id: str, history_id: int | None) -> None:
    t = _tables.get(table_id)
    if t and history_id:
        t['history_id'] = history_id


def apply_df_to_table(table_id: str, df: pd.DataFrame) -> bool:
    """用新的 DataFrame 覆盖内存表（协同写回普通编辑）。"""
    t = _tables.get(table_id)
    if not t:
        return False
    df = clean_data(df.copy())
    t['df'] = df
    t['summary'] = generate_summary(df)
    t['preview_data'] = df.head(100).fillna('').to_dict(orient='records')
    t['preview_columns'] = list(df.columns)
    t['dirty'] = True
    return True


def restore_table_as(table_id: str, df: pd.DataFrame, filename: str) -> str:
    """按指定 table_id 写入内存（用于协同源表重建）。"""
    global _active_table_id
    df = clean_data(df.copy())
    summary = generate_summary(df)
    _tables[table_id] = {
        'df': df,
        'filename': filename or '协同表格',
        'file_hash': '',
        'summary': summary,
        'preview_data': df.head(100).fillna('').to_dict(orient='records'),
        'preview_columns': list(df.columns),
        'history_id': None,
    }
    if _active_table_id is None:
        _active_table_id = table_id
    return table_id


# ============================================================
# 兼容旧接口
# ============================================================

def get_current_data() -> pd.DataFrame | None:
    t = get_active_table()
    return t['df'] if t else None


def get_current_summary() -> dict | None:
    t = get_active_table()
    return t['summary'] if t else None
