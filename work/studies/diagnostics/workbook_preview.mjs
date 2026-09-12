import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire('C:/Users/chdxm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/_study_preview.cjs');
const {FileBlob,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const root=process.cwd(),folder=path.join(root,'work/studies/diagnostics/workbook_previews');
const records=JSON.parse(await fs.readFile(path.join(folder,'index.json'),'utf8'));
const reports=[];
function column(n){let name='';for(;n;n=Math.floor((n-1)/26))name=String.fromCharCode(65+(n-1)%26)+name;return name;}
for(let b=0;b<records.length;b++){
  const record=records[b];
  const book=await SpreadsheetFile.importXlsx(await FileBlob.load(record.path));
  for(const sheet of record.sheets){
    for(let first=1;first<=sheet.columns;first+=8){
      const last=Math.min(first+7,sheet.columns),range=`${column(first)}1:${column(last)}${sheet.rows}`;
      const result=await book.render({sheetName:sheet.name,range,format:'png',scale:1});
      const output=path.join(folder,`${b}_${sheet.name}_${first}.png`);
      await fs.writeFile(output,new Uint8Array(await result.arrayBuffer()));
      reports.push({source:record.source,sheet:sheet.name,range,preview:output});
    }
  }
  console.log(`WORKBOOK_PREVIEW ${b+1}/${records.length} ${record.source}`);
}
await fs.writeFile(path.join(folder,'rendered.json'),JSON.stringify(reports,null,2));
