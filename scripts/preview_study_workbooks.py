"""Small faithful opening-view copies for bounded-memory workbook visual QA."""
import json
import sys
from copy import copy
from pathlib import Path
from openpyxl import Workbook,load_workbook


def Preview_Prepare(root,source_records=None):
    root=Path(root)
    if source_records is None:source_records=json.loads((root/'work/studies/diagnostics/workbook_readback.json').read_text(encoding='utf-8'))['outputs']
    output=root/'work/studies/diagnostics/workbook_previews';output.mkdir(parents=True,exist_ok=True);records=[]
    for number,record in enumerate(source_records):
        source=load_workbook(root/record['path']);preview=Workbook();preview.remove(preview.active);sheets=[]
        for original in source:
            sheet=preview.create_sheet(original.title);sheet.sheet_view.showGridLines=original.sheet_view.showGridLines
            for row in original.iter_rows(max_row=min(original.max_row,12)):
                for cell in row:
                    copied=sheet.cell(cell.row,cell.column,cell.value)
                    for name in ['font','fill','border','alignment','protection']:setattr(copied,name,copy(getattr(cell,name)))
                    copied.number_format=cell.number_format
            for name,dim in original.column_dimensions.items():sheet.column_dimensions[name].width=dim.width
            for row in range(1,min(original.max_row,12)+1):sheet.row_dimensions[row].height=original.row_dimensions[row].height
            sheets.append(dict(name=sheet.title,columns=original.max_column,rows=min(original.max_row,12)))
        path=output/f'book_{number}.xlsx';preview.save(path);preview.close();source.close()
        records.append(dict(source=record['path'],path=str(path),sheets=sheets))
    (output/'index.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':Preview_Prepare(Path(__file__).resolve().parents[1])
