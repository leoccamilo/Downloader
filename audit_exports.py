"""Excel exports for audit results that exceed one worksheet."""
import math
import os
from pathlib import Path
import tempfile

MAX_EXCEL_ROWS = 1048576


def write_audit_excel(frame, excel_writer, sheet_name='Sheet1', **kwargs):
    import pandas as pd
    header = kwargs.get('header', True)
    header_rows = int(header is not False)
    capacity = MAX_EXCEL_ROWS - kwargs.get('startrow', 0) - header_rows
    if len(frame) <= capacity:
        return frame.to_excel(excel_writer, sheet_name=sheet_name, **kwargs)
    if capacity <= 0:
        raise ValueError('No Excel rows available after the header.')
    if isinstance(frame.columns, pd.MultiIndex) or isinstance(frame.index, pd.MultiIndex):
        raise ValueError('Oversized audit exports require flat columns and index.')
    index = bool(kwargs.get('index', True))
    if kwargs.get('startcol', 0) + len(frame.columns) + int(index) > 16384:
        raise ValueError('Audit exceeds the Excel column limit.')
    pages = math.ceil(len(frame) / capacity)
    # Existing multi-sheet writers keep their own engine and lifecycle.
    if isinstance(excel_writer, pd.ExcelWriter):
        for number, start in enumerate(range(0, len(frame), capacity), 1):
            name = f'{sheet_name[:25]}_{number}'
            frame.iloc[start:start + capacity].to_excel(excel_writer, sheet_name=name, **kwargs)
        return
    from openpyxl import Workbook
    supported = {'index', 'header', 'na_rep', 'inf_rep', 'index_label', 'startrow', 'startcol', 'float_format', 'freeze_panes', 'engine'}
    if set(kwargs) - supported:
        raise ValueError(f'Unsupported streaming Excel options: {sorted(set(kwargs) - supported)}')
    target = Path(excel_writer)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.stem + '_', suffix='.xlsx', dir=target.parent)
    os.close(fd)
    book = Workbook(write_only=True)

    def value(item):
        if pd.isna(item):
            return kwargs.get('na_rep', '')
        if isinstance(item, float) and math.isinf(item):
            return ('-' if item < 0 else '') + kwargs.get('inf_rep', 'inf')
        if isinstance(item, float) and kwargs.get('float_format'):
            return float(kwargs['float_format'] % item)
        return item

    try:
        for number, start in enumerate(range(0, len(frame), capacity), 1):
            sheet = book.create_sheet(f'{sheet_name[:25]}_{number}')
            if kwargs.get('freeze_panes'):
                from openpyxl.utils import get_column_letter
                row, column = kwargs['freeze_panes']
                sheet.freeze_panes = f'{get_column_letter(column + 1)}{row + 1}'
            offset = [None] * kwargs.get('startcol', 0)
            for _ in range(kwargs.get('startrow', 0)):
                sheet.append([])
            if header_rows:
                labels = list(frame.columns) if header is True else list(header)
                if index:
                    labels.insert(0, kwargs.get('index_label', frame.index.name))
                sheet.append(offset + labels)
            for row in frame.iloc[start:start + capacity].itertuples(index=index, name=None):
                sheet.append(offset + [value(item) for item in row])
            print(f'Excel: {target.name}, aba {number}/{pages}, {min(capacity, len(frame) - start):,} linhas', flush=True)
        book.save(temporary)
        os.replace(temporary, target)
    finally:
        book.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
