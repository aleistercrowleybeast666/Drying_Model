"""Numerical Excel export using one lightweight library, as requested by the prompt."""
import csv
import json
import os
from copy import copy
from pathlib import Path
import numpy as np
from openpyxl import load_workbook
from .cases import Case_GetId, Case_LoadMesh, Case_GetSelected, Case_IterFields, Case_LoadInputs, Case_ReadStatus
from .sampling import Sampling_GetRadial
from .storage import Storage_WriteArray, Storage_WriteJson, Storage_HashFiles


def Export_Readback(path, names, times, arrays, radius_columns, outside_mask=None):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        assert wb.sheetnames == names, 'sheet names'
        for sheet, array in zip(wb, arrays):
            assert sheet.max_row == len(times)+1 and sheet.max_column == array.shape[1]+1, 'full row/column count'
            header = next(sheet.values)
            assert list(header[1:]) == radius_columns, 'radial headers'
            for index, cells in enumerate(sheet.iter_rows(min_row=2)):
                assert cells[0].data_type == 'n' and abs(cells[0].value-times[index]) < 1e-9, 'time numeric SI'
                assert cells[0].number_format == '0.0000'
                for col, cell in enumerate(cells[1:]):
                    expected = array[index, col]
                    if np.isnan(expected):
                        assert cell.value is None, 'out-of-domain blank'
                    else:
                        assert cell.data_type == 'n' and abs(cell.value-expected) < 2e-12, 'cache value consistency'
                        assert cell.number_format == '0.0000', 'display precision'
            assert np.all(np.diff(times)>0), 'event/regular endpoint deduplication'
    finally:
        wb.close()


def Export_WriteWorkbook(template, destination, times, arrays, radius_columns):
    wb = load_workbook(template)
    names = wb.sheetnames
    for sheet, array in zip(wb, arrays):
        header_style = copy(sheet['B1']._style)
        first_style = copy(sheet['A2']._style)
        sheet.delete_rows(2, sheet.max_row)
        sheet.delete_cols(2, sheet.max_column)
        sheet['A1'] = '时间\\到药材中心的距离'
        for column, value in enumerate(radius_columns, 2):
            cell = sheet.cell(1, column, value)
            cell._style = copy(header_style)
            if isinstance(value, (int,float)):
                cell.number_format = '0.0000'
            sheet.column_dimensions[cell.column_letter].width = 13
        sheet.column_dimensions['A'].width = 29
        sheet.freeze_panes = 'B2'
        for row, t in enumerate(times, 2):
            cell = sheet.cell(row, 1, float(t))
            cell._style = copy(first_style)
            cell.number_format = '0.0000'
            for column, value in enumerate(array[row-2], 2):
                cell = sheet.cell(row, column, None if np.isnan(value) else float(value))
                cell.number_format = '0.0000'
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix('.tmp.xlsx')
    try:
        wb.save(tmp)
        wb.close()
        Export_Readback(tmp, names, times, arrays, radius_columns)
        os.replace(tmp, destination)
    finally:
        wb.close()
        if tmp.exists():
            tmp.unlink()


def Export_Run(root, case_filter='all'):
    root = Path(root)
    from .outputs import Output_PrepareFolders
    Output_PrepareFolders(root)
    inputs = Case_LoadInputs(root)
    input_manifest = json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))
    val_path = root/'work/validation/summary.json'
    validation = json.loads(val_path.read_text(encoding='utf-8')) if val_path.exists() else {}
    manifest_path=root/'work/diagnostics/export_manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else dict(input_hash=input_manifest['hash'], outputs=[], official_source='1D')
    tables = root/'work/cache/exports'
    tables.mkdir(parents=True, exist_ok=True)
    for case, model, questions in [('q1',1,[1]), ('q23',3,[2,3]), ('q4',4,[4])]:
        if case_filter not in ('all',case):
            continue
        entry = validation.get(case+'_1d', {})
        case_id = Case_GetSelected(root,case,1)
        mesh = Case_LoadMesh(root,case_id)
        status = Case_ReadStatus(root, case_id)
        if entry.get('selected_id') != case_id or entry.get('selected_fingerprint') != status['fingerprint']:
            entry = {}
        if not status['complete'] or status['dim'] != 1:
            raise RuntimeError('EXPORT_FAILED: incomplete or non-1D source')
        samples = []
        for t, field in Case_IterFields(root, case_id):
            sampled, valid, surface, R = Sampling_GetRadial(field, t, model, inputs, np.arange(21)*.001, mesh)
            samples.append((t, sampled, valid, surface, R))
        if status['event']:
            with np.load(root/'work/cache'/case_id/'event.npz') as saved:
                et, estate = float(saved['time_s']), saved['state']
            sampled, valid, surface, R = Sampling_GetRadial(estate, et, model, inputs, np.arange(21)*.001, mesh)
            samples = [row for row in samples if abs(row[0]-et)>1e-8]+[(et,sampled,valid,surface,R)]
            samples.sort(key=lambda row:row[0])
        for q in questions:
            event = status['event'] if q >= 3 else None
            end = {1:1800.,2:10800.}.get(q, event['report_s'] if event else 259200.)
            selected = [row for row in samples if row[0]>0 and row[0]<=end+1e-8 and
                (q<=2 or abs(row[0]/60-round(row[0]/60))<1e-9 or (event and abs(row[0]-end)<1e-8))]
            if q<=2:
                selected = [row for row in selected if abs(row[0]-round(row[0]))<1e-8]
            times = np.array([row[0] for row in selected])
            values = np.stack([row[1] for row in selected])
            mask = np.stack([row[2] for row in selected])
            surface = np.stack([row[3] for row in selected])
            radii = np.array([row[4] for row in selected])
            temperature, moisture = values[:,0]-273.15, values[:,1]
            columns = [round(x*.1, 1) for x in range(21)]
            if q==4:
                moisture = np.column_stack((moisture, surface[:,1]))
                columns += ['药材表面']
            arrays = [temperature,moisture] if q<=2 else [moisture]
            destination = root/f'results/tables/result{q}.xlsx'
            provenance = root/f'work/diagnostics/result{q}_export.json'
            Export_WriteWorkbook(root/input_manifest['templates'][str(q)]['path'], destination, times, arrays, columns)
            payload = dict(question=q, case_id=case_id, fingerprint=status['fingerprint'], dimension=1,
                path=str(destination.relative_to(root)), status='GENERATED', numerical_validation=entry.get('numerical_status','PENDING'),
                rows=len(times), columns=len(columns)+1, event=event, workbook_hash=Storage_HashFiles([destination]),
                readback='PASSED: sheet names, all numeric cells, dimensions, time SI, precision, blanks, event deduplication, source')
            Storage_WriteJson(provenance, payload)
            Storage_WriteArray(tables/f'result{q}_full_precision.npz', time_s=times,
                temperature_C=temperature, moisture=moisture, valid_mask=np.isfinite(moisture),
                fixed_radius_valid_mask=mask, R_m=radii,
                surface_C=surface[:,1], fingerprint=status['fingerprint'])
            with (tables/f'result{q}_numeric.csv').open('w',newline='',encoding='utf-8-sig') as stream:
                writer=csv.writer(stream)
                writer.writerow(['time_s']+[f'C_r{c}_cm_kg_kg' if isinstance(c,float) else c for c in columns])
                for t,row in zip(times,moisture): writer.writerow([t]+['' if np.isnan(v) else v for v in row])
            if q==4:
                with (root/'results/q4/q4_radius_history.csv').open('w',newline='',encoding='utf-8-sig') as stream:
                    writer=csv.writer(stream); writer.writerow(['time_s','R_m','R_cm'])
                    writer.writerows(zip(times,radii,radii*100))
            key_times = ([100,300,600,900,1200,1500,1800] if q==1 else
                list(np.arange(1800,10801,1800)) if q==2 else list(np.arange(21600,end+1e-8,21600)))
            if q>=3 and event and all(abs(end-t)>1e-8 for t in key_times): key_times.append(end)
            with (root/f'results/q{q}/q{q}_key_values.csv').open('w',newline='',encoding='utf-8-sig') as stream:
                writer=csv.writer(stream)
                writer.writerow(['time_s','time_h','variable']+[f'r={x}cm' for x in [0,.5,1,1.5,2]]+(['药材表面'] if q==4 else []))
                for t in key_times:
                    indices=np.flatnonzero(np.abs(times-t)<1e-8)
                    if len(indices)!=1: raise RuntimeError('EXPORT_FAILED: missing exact key time')
                    index=indices[0]
                    for label,array in ([('temperature_C',temperature),('C_kg_kg',moisture)] if q<=2 else [('C_kg_kg',moisture)]):
                        row=list(array[index,[0,5,10,15,20]])
                        if q==4: row += [moisture[index,-1]]
                        writer.writerow([t,t/3600,label]+['' if np.isnan(v) else v for v in row])
            manifest['outputs']=[entry for entry in manifest['outputs'] if entry['question']!=q]
            manifest['outputs'].append(payload)
            manifest['outputs'].sort(key=lambda entry:entry['question'])
            Storage_WriteJson(root/'work/diagnostics/export_manifest.json', manifest)
    return manifest
