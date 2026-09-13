"""Small output-directory helper shared by the authoritative Excel exporter."""
from pathlib import Path


def Official_PrepareFolders(root):
    for name in ['results/tables',*[f'results/q{q}' for q in range(1,5)],
                 'work/cache','work/checkpoints','work/diagnostics','work/validation']:
        (Path(root)/name).mkdir(parents=True,exist_ok=True)
