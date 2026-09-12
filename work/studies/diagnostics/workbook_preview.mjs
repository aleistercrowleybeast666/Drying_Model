import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire('C:/Users/chdxm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/_study_preview.cjs');
const {FileBlob,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const root=process.cwd(),folder=path.join(root,'work/studies/diagnostics/workbook_previews');
const records=JSON.parse(await fs.readFile(path.join(folder,'index.json'),'utf8'));
const reports=[],inspections=[];
function column(n){let name='';for(;n;n=Math.floor((n-1)/26))name=String.fromCharCode(65+(n-1)%26)+name;return name;}
for(let b=0;b<records.length;b++){
  const record=records[b];
  const book=await SpreadsheetFile.importXlsx(await FileBlob.load(record.path));
  book.recalculate();
  inspections.push({source:record.source,errors:(await book.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},summary:'changed-view error scan'})).ndjson});
  for(const sheet of record.sheets){
    const first=sheet.first_column??1;
    inspections.push({source:record.source,sheet:sheet.name,values:(await book.inspect({kind:'table',range:`'${sheet.name}'!${column(first)}1:${column(Math.min(first+3,sheet.columns))}5`,include:'values,formulas',tableMaxRows:5,tableMaxCols:4})).ndjson});
    for(let first=sheet.first_column??1;first<=sheet.columns;first+=sheet.column_block??8){
      for(let row=1;row<=sheet.rows;row+=sheet.row_block??sheet.rows){
      const last=Math.min(first+(sheet.column_block??8)-1,sheet.columns),range=`${column(first)}${row}:${column(last)}${Math.min(row+(sheet.row_block??sheet.rows)-1,sheet.rows)}`;
      const result=await book.render({sheetName:sheet.name,range,format:'png',scale:1});
      const output=path.join(folder,`${b}_${sheet.name}_${first}_${row}.png`);
      await fs.writeFile(output,new Uint8Array(await result.arrayBuffer()));
      reports.push({source:record.source,sheet:sheet.name,range,preview:output});
      }
    }
  }
  console.log(`WORKBOOK_PREVIEW ${b+1}/${records.length} ${record.source}`);
}
await fs.writeFile(path.join(folder,'rendered.json'),JSON.stringify(reports,null,2));

await fs.writeFile(path.join(folder,'inspections.json'),JSON.stringify(inspections,null,2));
