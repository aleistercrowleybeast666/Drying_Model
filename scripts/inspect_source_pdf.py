"""Read-only PDF rendering with locally installed Qt; not a generated report."""
import os
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication
from PySide6.QtPdf import QPdfDocument
from PySide6.QtGui import QImage, QPainter

root=Path(__file__).resolve().parents[1]
app=QApplication([])
document=QPdfDocument()
document.load(str(root/'data/raw/A题.pdf'))
folder=root/'work/validation/source_pdf_preview'
folder.mkdir(parents=True,exist_ok=True)
for page in range(document.pageCount()):
    size=document.pagePointSize(page)
    image=document.render(page,QSize(int(size.width()*1.4),int(size.height()*1.4)))
    canvas=QImage(image.size(),QImage.Format.Format_RGB32)
    canvas.fill(0xffffffff)
    painter=QPainter(canvas)
    painter.drawImage(0,0,image)
    painter.end()
    canvas.save(str(folder/f'page_{page+1}.png'))
print(document.pageCount())
