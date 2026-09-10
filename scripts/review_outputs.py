"""Machine-readable delivery checks plus representative workbook previews."""
import json
import sys
from pathlib import Path
import numpy as np
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from drying.storage import Storage_WriteJson


def Review_Run():
    manifest=json.loads((root/'results/manifest.json').read_text(encoding='utf-8'))
    folder=root/'results/validation/workbook_previews'; folder.mkdir(parents=True,exist_ok=True)
    font_path=Path('C:/Windows/Fonts/msyh.ttc')
    font=ImageFont.truetype(str(font_path),18)
    records=[]
    for entry in manifest['outputs']:
        with np.load(root/f"results/tables/result{entry['question']}_full_precision.npz") as cache:
            assert cache['valid_mask'].shape==cache['moisture'].shape
            assert np.array_equal(cache['valid_mask'],np.isfinite(cache['moisture']))
        path=root/entry['path']; wb=load_workbook(path,read_only=True,data_only=True)
        for sheet in wb:
            # Read only sample rows; actual export already checked every numeric cell.
            all_rows=list(sheet.values)
            indices=[0,1,2,3,len(all_rows)//2,len(all_rows)-1]
            columns=[0,1,6,11,16,21]+([22] if entry['question']==4 else [])
            width=260+160*(len(columns)-1); height=70+48*len(indices)
            canvas=Image.new('RGB',(width,height),'white'); draw=ImageDraw.Draw(canvas)
            draw.text((15,15),f"result{entry['question']} · {sheet.title} · 已保存Excel抽样预览",font=font,fill='#16384c')
            for row_no,index in enumerate(indices):
                top=65+48*row_no
                for cno,col in enumerate(columns):
                    left=0 if cno==0 else 260+160*(cno-1)
                    right=260 if cno==0 else left+160
                    draw.rectangle((left,top,right,top+48),fill='#e7eff3' if row_no==0 else ('#f4f7f9' if row_no%2==0 else 'white'),outline='#cdd8de')
                    value=all_rows[index][col]
                    text='' if value is None else (f'{value:.4f}' if isinstance(value,(int,float)) else str(value))
                    if row_no==0 and cno==0: text='时间 / s；径向 / cm'
                    draw.text((left+10,top+12),text,font=font,fill='#17394c')
            preview=folder/f"result{entry['question']}_{sheet.title}.png"; canvas.save(preview)
            records.append(dict(file=entry['path'],sheet=sheet.title,rows=sheet.max_row,columns=sheet.max_column,
                candidate=entry['status']!='final',last_time_s=all_rows[-1][0],preview=str(preview.relative_to(root))))
        wb.close()
    Storage_WriteJson(root/'results/validation/delivery_checks.json',dict(workbooks=records))
    print(json.dumps(records,ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    Review_Run()
