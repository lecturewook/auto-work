// Optional developer-only browser check. No browser libraries are used by the app.
const {chromium}=require(process.env.BUDGET_PLAYWRIGHT||'playwright-core');
const {spawn}=require('child_process');
const fs=require('fs'),os=require('os'),path=require('path');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'budget-browser-'));
 const server=spawn(path.join(root,'.venv/bin/python'),['-B','run_web.py','--no-browser'],{cwd:root});
 let browser;try{
 const url=await new Promise((resolve,reject)=>{let out='';const timer=setTimeout(()=>reject(Error('startup timeout')),15000);server.stdout.on('data',b=>{out+=b;const m=out.match(/LOCAL_WEB_READY (\S+)/);if(m){clearTimeout(timer);resolve(m[1]);}});server.on('exit',c=>{clearTimeout(timer);reject(Error('server exited '+c));});server.stderr.on('data',b=>process.stderr.write(b));});
 browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-background-networking']});
 const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[],external=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){external.push(route.request().url());return route.abort();}return route.continue();});
 await page.goto(url);await page.getByText('내 PC 전용 웹에 연결했습니다.',{exact:false}).waitFor();
 await page.locator('#path').fill(path.join(temp,'demo'));await page.locator('#demo').click();
 await page.getByText('가상 파일 6개를 가져왔습니다.',{exact:false}).waitFor();
 if(await page.locator('#filetable tr').count()!==7)throw Error('Expected six files');
 await page.locator('#showobs').click();
 if(await page.locator('#datatable tr').count()!==25)throw Error('Expected 24 observations');
 await page.locator('#datatable button').first().click();
 await page.locator('#reviewer').fill('브라우저 시험자');await page.locator('#reason').fill('가상 원문과 의미 확인');
 await page.getByRole('button',{name:'연결 확인하여 저장',exact:true}).click();
 await page.locator('#detail').waitFor({state:'hidden'});
 await page.locator('#draft').click();await page.getByRole('button',{name:/사본 다운로드:/}).waitFor();
 fs.mkdirSync(path.join(root,'docs/demo'),{recursive:true});await page.screenshot({path:path.join(root,'docs/demo/06-local-web.png'),fullPage:true});
 page.on('dialog',d=>d.accept());await page.locator('#shutdown').click();
 await page.getByText('프로그램을 종료했습니다.',{exact:false}).waitFor();
 if(errors.length||external.length)throw Error(JSON.stringify({errors,external}));
 console.log(JSON.stringify({browser:'Chromium on Linux',files:6,observations:24,manual_mapping:true,draft_export:true,shutdown:true,page_errors:errors,external_page_requests:external,windows_edge_validated:false},null,2));
 }finally{if(browser)await browser.close();server.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
