'use strict';
// Test renderer only: production operations all arrive through EditorNativeClient.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
    const area = process.env.SPRITESUITE_NATIVE_TEST_AREA;
    const origin = process.env.SPRITESUITE_NATIVE_TEST_ORIGIN;
    if (!area || !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin)) throw Error('Isolated fixture environment required.');
    let browser, socket;
    try {
        const profile = path.join(area, 'browser-profile');
        browser = spawn(process.env.SPRITESUITE_CHROMIUM || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
            ['--headless=new','--no-first-run','--disable-gpu','--disable-background-networking',
             '--no-default-browser-check','--disable-component-update','--remote-allow-origins=*',
             '--user-data-dir=' + profile,'--remote-debugging-port=0','about:blank'],
            { stdio:'ignore', windowsHide:true });
        let port;
        for (let i=0;i<130;i++) {
            try { port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split(/\r?\n/)[0]); }
            catch(e) { if(!['EBUSY','EACCES','ENOENT'].includes(e.code)) throw e; }
            if(port)break; if(browser.exitCode!==null)throw Error('Fixture browser exited'); await delay(100);
        }
        if(!port)throw Error('No fixture browser debug endpoint');
        const pages=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
        socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
        await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
        let serial=0;const pending=new Map(),errors=[];
        socket.onmessage=event=>{
            const m=JSON.parse(event.data);
            if(m.id&&pending.has(m.id)){const item=pending.get(m.id);pending.delete(m.id);clearTimeout(item.timer);
                if(m.error)item.reject(Error(JSON.stringify(m.error)));else item.resolve(m.result||{});}
            else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);
        };
        function send(method,params={}){return new Promise((resolve,reject)=>{
            const id=++serial,timer=setTimeout(()=>reject(Error('Fixture CDP timeout')),15000);
            pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});}
        await send('Runtime.enable');await send('Page.enable');
        await send('Emulation.setDeviceMetricsOverride',{width:1280,height:720,deviceScaleFactor:1,mobile:false});
        await send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:path.join(area,'downloads')});
        await send('Page.navigate',{url:origin});
        let paused=false;
        while(true){
            let control={};
            try{control=JSON.parse(fs.readFileSync(path.join(area,'renderer-control.json'),'utf8'));}
            catch(e){if(!['ENOENT','EBUSY','EACCES'].includes(e.code)&&!(e instanceof SyntaxError))throw e;}
            if(control.stop)break;
            if(typeof control.pause==='boolean'&&control.pause!==paused){
                await send('Emulation.setScriptExecutionDisabled',{value:control.pause});paused=control.pause;
                fs.writeFileSync(path.join(area,'renderer-status.json'),JSON.stringify({paused}));
            }
            await delay(100);
        }
        if(errors.length)throw Error('Fixture renderer errors: '+errors.join('; '));
        fs.writeFileSync(path.join(area,'renderer-result.json'),JSON.stringify({passed:true,pageErrors:errors}));
        await send('Browser.close');
    }finally{
        if(socket)socket.close();
        if(browser&&browser.exitCode==null)browser.kill();
    }
})().catch(error=>{console.error(error);process.exitCode=1;});
