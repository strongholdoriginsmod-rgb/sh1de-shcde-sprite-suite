"""Offline UI regression tests, using the actual built HTML and native Chromium APIs.
Run: python tests/test_browser.py --browser /path/to/chromium
No origin-policy or managed-browser-policy changes are made. set_content loads the
standalone document without navigating: native IndexedDB durability is not tested.
"""
from pathlib import Path
import argparse,io,json,time,zipfile,hashlib,traceback,subprocess
from xml.etree import ElementTree as ET
from PIL import Image,ImageChops
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/'tests'/'fixtures';OUT=ROOT/'tests'/'results';OUT.mkdir(exist_ok=True)
parser=argparse.ArgumentParser();parser.add_argument('--browser',default='/usr/bin/chromium');args=parser.parse_args()
subprocess.run(['node',str(ROOT/'tests/generate_capacity.cjs')],check=True)
html=(ROOT/'Stronghold_Sprite_Editor.html').read_text(encoding='utf-8');results=[];errors=[];requests=[]

def check(name,fn):
 start=time.monotonic();fn();results.append({'name':name,'passed':True,'seconds':round(time.monotonic()-start,3)});print('PASS',name,flush=True)
def assert_(condition,why='assertion failed'):
 if not condition:raise AssertionError(why)
def snap(page):return page.evaluate('SpriteEditor.inspect()')
def waitfor(page,expression,timeout=20):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  if page.evaluate('() => '+expression):return
  page.wait_for_timeout(40)
 raise AssertionError('Timed out: '+expression)
def quiet(page):waitfor(page,"!document.getElementById('busy-dialog').open");page.wait_for_timeout(80)
def view(page,name):page.locator(f'[data-view="{name}"]').click();page.wait_for_timeout(100)
def panel(page,name):page.locator(f'[data-panel="{name}"]').click();page.wait_for_timeout(50)
def menu(page,action):page.locator('.menu summary').click();page.locator(f'.menu [data-action="{action}"]').click()
def export(page,kind,filename,scope=None):
 page.locator('header [data-action="export"]').click();page.get_by_label('Format',exact=True).select_option(kind)
 if scope:page.get_by_label('Umfang',exact=True).select_option(scope)
 if kind in ('mod','semod'):page.locator('[name="ack"]').check()
 with page.expect_download(timeout=20000) as d:page.locator('#modal-submit').click()
 file=OUT/filename;d.value.save_as(file);quiet(page);waitfor(page,"!document.getElementById('modal').open");return file

def import_(page,kind,paths,source='shde',expect_fail=False):
 page.locator('header [data-action="import"]').click();page.get_by_label('Import',exact=True).select_option(kind);page.get_by_label('Herkunft',exact=True).select_option(source)
 with page.expect_file_chooser() as chooser:page.get_by_role('button',name='Dateien auswählen…',exact=True).click()
 chooser.value.set_files([str(p) for p in paths]);page.locator('#modal-submit').click();quiet(page)
 if expect_fail:assert_(page.locator('#modal-error').is_visible());page.locator('[data-action="close-modal"]').first.click()
 else:
  if page.locator('#modal-error').is_visible():raise AssertionError(page.locator('#modal-error').inner_text())
  waitfor(page,"!document.getElementById('modal').open")

def project_open(page,file):
 menu(page,'open') # Click opens native picker.

def png(path):return Image.open(path).convert('RGBA')
def equal_images(a,b):assert_(a.size==b.size,'image dimensions differ');assert_(a.tobytes()==b.tobytes(),'RGBA pixels differ')
def empty_browser_page(ctx):
 p=ctx.new_page();p.on('pageerror',lambda e:errors.append(str(e)));p.on('request',lambda r:requests.append(r.url));p.set_content(html);p.wait_for_timeout(180);return p

with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=args.browser,headless=True,args=['--no-sandbox'])
 ctx=browser.new_context(viewport={'width':1440,'height':960},device_scale_factor=1,accept_downloads=True)
 page=empty_browser_page(ctx)
 try:
  check('Unmodified standalone HTML initializes without network resources',lambda:assert_(snap(page)['state']['frames']==[] and snap(page)['view']=='scene' and not requests))
  check('Unavailable local recovery is handled without blocking editing',lambda:assert_(page.locator('#recovery-status').inner_text()=='Ohne Autosicherung'))
  menu(page,'demo');quiet(page)
  check('Built-in synthetic 5x5 example loads 25 sprites',lambda:assert_(len(snap(page)['state']['frames'])==25))
  for name in ['scene','sprite','animation','atlas','split']:
   view(page,name);check(f'Workspace {name} changes without errors',lambda name=name:assert_(snap(page)['view']==name))
  view(page,'scene');page.screenshot(path=str(OUT/'editor-1440.png'))
  merged=export(page,'merged','example.png')
  check('Merged PNG is emitted with alpha and nonzero artwork',lambda:assert_(png(merged).getbbox() is not None and png(merged).getextrema()[3][0]==0))
  original=export(page,'originals','example-originals.zip')
  ora=export(page,'ora','example.ora')
  project=export(page,'project','example.shsprite')
  def original_check():
   with zipfile.ZipFile(project) as z,zipfile.ZipFile(original) as o:
    data=json.loads(z.read('project.json'));assets={a['id']:a for a in data['assets']}
    for f in data['frames']:assert_(o.read(f['name'])==z.read(assets[f['originalId']]['path']))
  check('Project stores every demo original byte-for-byte',original_check)
  def ora_check():
   with zipfile.ZipFile(ora) as z:
    assert_(z.infolist()[0].filename=='mimetype' and z.infolist()[0].compress_type==0)
    tree=ET.fromstring(z.read('stack.xml'));assert_(len(tree.findall('.//layer'))==25)
    equal_images(Image.open(io.BytesIO(z.read('mergedimage.png'))).convert('RGBA'),png(merged))
  check('OpenRaster validates independently and matches merged PNG',ora_check)
  # Use exact source origin for new disjoint cuts, then actually export/reassemble.
  view(page,'split');page.locator('[data-action="scene-to-split"]').click();quiet(page)
  check('Compose-to-cut transfers exact geometry instead of guessing the anchor',lambda:assert_(snap(page)['state']['split']['settings']['a']==5 and snap(page)['state']['split']['anchorX']>0))
  cut=export(page,'split','example-cut.zip')
  def cut_check():
   source=png(merged);out=Image.new('RGBA',source.size)
   with zipfile.ZipFile(cut) as z:
    meta=json.loads(z.read('schnitt.json'));assert_(len(meta['tiles'])==25)
    # Disjoint masks, so every nontransparent sample is preserved exactly.
    for t in meta['tiles']:
     im=Image.open(io.BytesIO(z.read(t['name']))).convert('RGBA');layer=Image.new('RGBA',source.size);layer.paste(im,(t['x'],t['y']));out=Image.alpha_composite(out,layer)
   equal_images(out,source)
  check('Cut ZIP independently reassembles to the same RGBA image',cut_check)
  ownership=export(page,'ownership','example-ownership.png')
  before=snap(page)['state']['split']['mapId'];page.locator('[data-action="brush-tool"]').click()
  page.locator('#brush-erase').check();page.locator('#brush-radius').fill('8')
  box=page.locator('#viewport').bounding_box();page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down();page.mouse.move(box['x']+box['width']/2+20,box['y']+box['height']/2+10,steps=5);page.mouse.up();quiet(page)
  check('Ownership brush commits one undoable stroke',lambda:assert_(snap(page)['state']['split']['mapId']!=before))
  page.locator('#undo').click();quiet(page)
  check('Undo restores the exact ownership map',lambda:assert_(snap(page)['state']['split']['mapId']==before))
  page.locator('[data-action="split-transfer"]').click();quiet(page)
  check('Cut tiles become an independently editable second group',lambda:assert_(len(snap(page)['state']['scenes'])==2 and len(snap(page)['state']['frames'])==50 and snap(page)['view']=='scene'))
  # Reload UI output through native file input, not internal setters.
  restored=empty_browser_page(ctx)
  with restored.expect_file_chooser() as chooser:menu(restored,'open')
  chooser.value.set_files(str(project));quiet(restored)
  check('Saved project reopens through the normal UI',lambda:assert_(len(snap(restored)['state']['frames'])==25 and not snap(restored)['dirty']))
  reexport=export(restored,'originals','reopened-originals.zip')
  check('Original export survives project reopen without changed bytes',lambda:assert_(zipfile.ZipFile(reexport).read('tile_beispiel-0.png')==zipfile.ZipFile(original).read('tile_beispiel-0.png')))
  legacy=empty_browser_page(ctx)
  with legacy.expect_file_chooser() as chooser:menu(legacy,'open')
  chooser.value.set_files(str(FIX/'legacy-v0.1.json'));quiet(legacy)
  check('Actual previous v0.1 demo opens through the file dialog',lambda:assert_(len(snap(legacy)['state']['frames'])==25 and snap(legacy)['state']['scenes'][0]['source']=='custom'))
  legacy.close()
  trimming=empty_browser_page(ctx)
  import_(trimming,'png',[FIX/'trim-0.png'],source='custom');import_(trimming,'metadata',[FIX/'trim-meta.json'],source='custom')
  trimming.locator('#viewport').click();trimming.keyboard.press('ArrowRight');trimming.keyboard.press('ArrowUp');quiet(trimming)
  original_frame=snap(trimming)['state']['frames'][0]
  trimming.get_by_role('button',name='Transformieren…',exact=True).click();trimming.get_by_label('Operation',exact=True).select_option('trim');trimming.locator('#modal-submit').click();quiet(trimming)
  trimmed=snap(trimming)['state']['frames'][0]
  check('Transparent trim records nonzero anchor compensation',lambda:assert_(trimmed['imageId']!=original_frame['imageId'] and (trimmed['trimOffsetX']!=0 or trimmed['trimOffsetY']!=0)))
  trimming.get_by_role('button',name='Originalzustand',exact=True).click();quiet(trimming)
  def reset_check():
   f=snap(trimming)['state']['frames'][0]
   for key in ['imageId','maskId','dx','dy','pivot','ppu']:assert_(f[key]==original_frame[key],key)
   assert_(f['trimOffsetX']==f['trimOffsetY']==0)
  check('Original reset removes trim compensation while preserving manual offsets',reset_check)
  trimming.close()
  capacity=empty_browser_page(ctx)
  with capacity.expect_file_chooser() as chooser:menu(capacity,'open')
  chooser.value.set_files(str(FIX/'capacity.shsprite'));quiet(capacity)
  check('4096-frame project renders with a bounded virtual file list',lambda:assert_(len(snap(capacity)['state']['frames'])==4096 and capacity.locator('.asset-row').count()<50))
  capacity.locator('#asset-list').evaluate('(node)=>{node.scrollTop=node.scrollHeight}')
  capacity.wait_for_timeout(150)
  check('Virtual file list reaches the last frame without expanding all rows',lambda:assert_(capacity.locator('.asset-row').count()<50 and 'body_capacity-4095.png' in capacity.locator('#asset-space').inner_text()))
  capacity.close()
  # Pixel editing and SHDE -> SHCDE workflow with independent, synthetic fixture PNGs.
  real=empty_browser_page(ctx);page=real
  import_(real,'png',sorted((FIX/'series').glob('*.png')))
  check('PNG series imports color-mask pairs and SHDE provenance',lambda:assert_(len(snap(real)['state']['frames'])==3 and all(f['maskId'] for f in snap(real)['state']['frames']) and snap(real)['state']['scenes'][0]['source']=='shde'))
  import_(real,'metadata',[FIX/'source-meta.json'])
  check('Source metadata is imported explicitly',lambda:assert_(all(f['pivot']=={'x':.25,'y':.125} and f['metadataStatus']=='imported' for f in snap(real)['state']['frames'])))
  import_(real,'mapping',[FIX/'mapping.csv'])
  import_(real,'referenceMetadata',[FIX/'target-meta.json'])
  import_(real,'reference',sorted((FIX/'references').glob('*.png')))
  check('Reference PNG import preserves metadata imported before the images',lambda:assert_(all(r['pivot']=={'x':.375,'y':.25} and r['ppu']==64 for r in snap(real)['state']['references'])))
  check('Target mapping and independent reference metadata match',lambda:assert_(len(snap(real)['state']['references'])==3 and [f['targetName'] for f in snap(real)['state']['frames']]==['body_target-0','body_target-1','body_target-2']))
  # Real UI preflight and package data.
  menu(real,'project');real.get_by_label('Autor',exact=True).fill('Regression Test');real.get_by_label('Mod-ID',exact=True).fill('test-port');real.locator('#modal-submit').click();quiet(real)
  panel(real,'target');real.get_by_label('Material',exact=True).select_option('TeamColour');quiet(real)
  panel(real,'checks')
  check('Valid target references clear all formal export errors',lambda:assert_('0 Fehler' in real.locator('.issue-summary').inner_text()))
  atlas=export(real,'atlas','workflow-atlas.zip')
  mod=export(real,'mod','workflow-mod.zip');semod=export(real,'semod','workflow-mod.semod')
  def mod_check():
   with zipfile.ZipFile(mod) as z:
    prefix='BepInEx/plugins/test-port/';info=json.loads(z.read(prefix+'info.json'));assert_(info['Manifest']==0 and info['NetworkMode']==0 and info['Dependencies'][0]['GUID']=='000shcdese')
    report=json.loads(z.read(prefix+'port-report.json'));assert_(report['inGameTested'] is False and len(report['mappings'])==3)
    d=json.loads(z.read(prefix+'Override/Atlas/body_target/atlas.json'));a=Image.open(io.BytesIO(z.read(prefix+'Override/Atlas/body_target/atlas.png'))).convert('RGBA');m=Image.open(io.BytesIO(z.read(prefix+'Override/Atlas/body_target/atlas_m.png'))).convert('RGBA')
    for i,f in enumerate(d['frames']):
     r=f['rect'];crop=(r['x'],a.height-r['y']-r['h'],r['x']+r['w'],a.height-r['y']);equal_images(a.crop(crop),png(FIX/'series'/f'body_source-{7+i}.png'));equal_images(m.crop(crop),png(FIX/'series'/f'body_source-{7+i}_m.png'));assert_(f['pivot']=={'x':.375,'y':.25})
   with zipfile.ZipFile(semod) as z:assert_('info.json' in z.namelist() and 'Override/Atlas/body_target/atlas.png' in z.namelist())
  check('Actual downloaded ZIP and SEMOD contain exact pixels, masks and target pivots',mod_check)
  panel(real,'target');real.get_by_label('Ersetzungsweg',exact=True).select_option('sprites');quiet(real)
  single=export(real,'mod','single-mod.zip')
  def single_check():
   with zipfile.ZipFile(single) as z:
    for i in range(3):
     base=f'BepInEx/plugins/test-port/Override/Sprites/body_target-{i}'
     assert_(z.read(base+'.png')==(FIX/'series'/f'body_source-{i+7}.png').read_bytes());assert_(z.read(base+'_m.png')==(FIX/'series'/f'body_source-{i+7}_m.png').read_bytes())
  check('Single override exports source PNG bytes exactly and only after dimension validation',single_check)
  # Full group resize changes image/mask together. Observe output independently.
  panel(real,'properties');view(real,'sprite');real.locator('#viewport').click();real.keyboard.press('Control+a');quiet(real)
  before_ids=[f['imageId'] for f in snap(real)['state']['frames']]
  real.get_by_role('button',name='Transformieren…',exact=True).click();real.get_by_label('Skalierung · %',exact=True).fill('200');real.locator('#modal-submit').click();quiet(real)
  transformed=export(real,'tiles','transformed.zip')
  def transformed_check():
   with zipfile.ZipFile(transformed) as z:
    for i in range(3):
     for suffix in ['','_m']:
      name=f'body_source-{7+i}{suffix}.png';out=Image.open(io.BytesIO(z.read(name))).convert('RGBA');src=png(FIX/'series'/name);equal_images(out,src.resize((src.width*2,src.height*2),Image.Resampling.NEAREST))
   assert_(all(f['ppu']==128 for f in snap(real)['state']['frames']))
  check('Batch nearest-neighbor resize applies to masks and PPU coherently',transformed_check)
  panel(real,'checks');check('Single override now fails dimensions instead of silently installing resized assets',lambda:assert_('0 Fehler' not in real.locator('.issue-summary').inner_text()))
  real.locator('#undo').click();quiet(real)
  check('Undo restores all original image IDs after batch transformation',lambda:assert_([f['imageId'] for f in snap(real)['state']['frames']]==before_ids))
  real.locator('#redo').click();quiet(real);real.locator('#undo').click();quiet(real)
  check('Redo and second undo preserve synchronized color and mask dimensions',lambda:assert_(all(f['ppu']==64 for f in snap(real)['state']['frames'])))
  view(real,'animation');real.locator('#fps').fill('1');real.locator('#fps').press('Tab');idx=snap(real)['animIndex'];real.locator('[data-action="play"]').click();real.wait_for_timeout(1150)
  check('Animation playback advances using the selected sequence',lambda:assert_(snap(real)['playing'] and snap(real)['animIndex']!=idx))
  real.locator('[data-action="play"]').click();idx=snap(real)['animIndex'];real.wait_for_timeout(250)
  check('Animation pauses without moving the frame index',lambda:assert_(not snap(real)['playing'] and snap(real)['animIndex']==idx))
  # Failed import transaction must not change anything or navigate to an invalid group.
  old=snap(real);import_(real,'png',[FIX/'c6_d8_i0.png',FIX/'broken'/'broken-0.png'],expect_fail=True);new=snap(real)
  check('Corrupt multi-file import rolls back state, group selection and asset store',lambda:assert_(new['state']==old['state'] and new['groupId']==old['groupId'] and new['assetCount']==old['assetCount']))
  # Explicit anti-loss guard for reducing number of cut cells.
  view(restored,'split');restored.locator('[data-action="scene-to-split"]').click();quiet(restored);restored.get_by_label('Links',exact=True).fill('2');restored.get_by_label('Links',exact=True).press('Tab');quiet(restored)
  check('Reducing the cut grid regenerates a valid map atomically',lambda:assert_(snap(restored)['state']['split']['settings']['a']==2))
  restored.locator('#undo').click();quiet(restored);check('Grid change is undoable including the original ownership map',lambda:assert_(snap(restored)['state']['split']['settings']['a']==5))
  # Responsive UI and native layout checks, actual screenshots of all key widths.
  page=real;panel(real,'properties');view(real,'scene')
  for w,h in [(1920,1080),(1440,960),(1024,768),(768,1024),(390,844)]:
   real.set_viewport_size({'width':w,'height':h});real.wait_for_timeout(120);real.screenshot(path=str(OUT/f'layout-{w}.png'))
   check(f'No document overflow at {w} x {h}',lambda:assert_(real.evaluate('document.documentElement.scrollWidth<=innerWidth && document.documentElement.scrollHeight<=innerHeight')))
  real.locator('[data-action="toggle-inspector"]').click();real.wait_for_timeout(100)
  check('Mobile inspector opens as a drawer',lambda:assert_('open' in real.locator('#inspector').get_attribute('class')))
  real.locator('[data-action="toggle-inspector"]').click();real.locator('[data-action="toggle-files"]').click();real.wait_for_timeout(100)
  check('Mobile file list opens independently',lambda:assert_('open' in real.locator('#files-panel').get_attribute('class')))
  real.set_viewport_size({'width':1440,'height':960});view(real,'atlas');real.screenshot(path=str(OUT/'atlas-1440.png'))
  # OpenRasters/exports are tested; original preserved through save/reopen after actual imports.
  wf=export(real,'project','workflow.shsprite')
  check('Project save finishes and clears unsaved indicator',lambda:assert_(not snap(real)['dirty']))
  check('No unhandled JavaScript exceptions throughout workflows',lambda:assert_(not errors,str(errors)))
  check('No application network requests throughout workflows',lambda:assert_(not requests,str(requests)))
 except Exception:
  page.screenshot(path=str(OUT/'failure.png'));(OUT/'failure.txt').write_text(traceback.format_exc());raise
 finally:
  report={'htmlSHA256':hashlib.sha256(html.encode('utf-8')).hexdigest(),'browser':browser.version,'load':'unmodified HTML via page.set_content; opaque origin','nativeIndexedDBTested':False,'directFileNavigationTested':False,'gameTested':False,'passed':len(results),'checks':results,'pageErrors':errors,'networkRequests':requests}
  (OUT/'browser-report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False));browser.close()
print('BROWSER CHECKS:',len(results))
