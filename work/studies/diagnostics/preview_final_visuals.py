"""Contact sheets and selected decoded frames for local visual QA only."""
from pathlib import Path
import json
import argparse
from PIL import Image,ImageOps,ImageDraw

parser=argparse.ArgumentParser()
parser.add_argument('--figures-only',action='store_true')
args=parser.parse_args()
root=Path(__file__).resolve().parents[3]
output=root/'work/studies/diagnostics/visual_previews';output.mkdir(parents=True,exist_ok=True)
figures=sorted((root/'results/studies/figures').glob('*.png'))
canvas=Image.new('RGB',(1800,1320),'white');draw=ImageDraw.Draw(canvas)
for index,path in enumerate(figures):
    with Image.open(path) as source:thumb=ImageOps.contain(source.convert('RGB'),(600,415))
    x=(index%3)*600;y=(index//3)*440
    canvas.paste(thumb,(x+(600-thumb.width)//2,y+20));draw.text((x+10,y+4),path.name,fill='black')
canvas.save(output/'figures_contact_sheet.png')
report=[]
for path in ([] if args.figures_only else sorted((root/'results/studies/animations').glob('*.gif'))):
    if path.name.endswith('.tmp.gif'):continue
    with Image.open(path) as gif:
        frames=sorted(set([0,1,10,119,120,gif.n_frames-1]))
        for frame in frames:
            gif.seek(frame);target=output/f'{path.stem}_{frame:03d}.png';gif.convert('RGB').save(target)
            report.append(dict(source=str(path),frame=frame,path=str(target),size=list(gif.size)))
(output/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(output)
