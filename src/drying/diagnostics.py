import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path


def Diagnostics_Open(root):
    folder = Path(root) / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('drying')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        for handler in (logging.StreamHandler(), logging.FileHandler(folder/'run.log', encoding='utf-8')):
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    return logger


def Diagnostics_Record(root, code, severity='INFO', **fields):
    entry = dict(wall_time_utc=datetime.now(timezone.utc).isoformat(),
                 code=code, severity=severity, **fields)
    folder = Path(root)/'logs'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + '\n')
    if severity == 'ERROR' or code == 'RK_STEP_REJECTED':
        details = Path(root)/'work/diagnostics'
        details.mkdir(parents=True, exist_ok=True)
        with (details/'failures.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + '\n')
    logging.getLogger('drying').log(getattr(logging, severity), '%s %s', code,
                                   json.dumps(fields, ensure_ascii=False))


def Diagnostics_RecordException(root, code, error, **fields):
    Diagnostics_Record(root, code, 'ERROR', exception_type=type(error).__name__,
                       message=str(error), traceback=traceback.format_exc(), **fields)
