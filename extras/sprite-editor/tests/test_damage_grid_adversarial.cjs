'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('../src/core.js'),I=require('../src/io.js'),D=require('../src/damage.js'),DI=require('../src/damage_io.js');
function make(a,b,height,order='ascending',k=0){
 const s=C.scene({a,b,width:64,height,category:'building',anchor:'bottom',order,padding:0});
 const ps=C.positions(s),W=(a+b)*40+72,H=(a+b)*34+96;
 const ax=Math.round(W/2),ay=H-16,src=C.image(W,H);
 const map=C.partition(src,s,ax,ay,true);
 for(let y=0;y<H;y++) for(let x=0;x<W;x++){
   const i=y*W+x,owner=map[i];
   if(owner<0)continue;
   const p=ps[owner],left=ax+p.x-32,right=left+64,bottom=ay+p.bottom;
   if(x<left||x>=right||y>bottom||y<bottom-80)continue;
   if(((x+y*2+k)%13)<3)continue;
   const idx=i*4;src.data[idx]=((x*23+y+17)%255)+1;
   src.data[idx+1]=(y*3+42)%254+1;
   src.data[idx+2]=((x^y)+1)%255;
   src.data[idx+3]=(x+y+k)%17===0?130:255;
 }
 const out=C.split(src,map,s,ax,ay,null,{overlap:1,rearShare:true});
 const store=new I.AssetStore(),state=I.blank(),gid='g_base';
 state.scenes.push({id:gid,name:'tile_fuzz',source:'custom',settings:s});
 for(const t of out.tiles){
  const imageId=store.add(t.image),f=I.makeFrame('tile_fuzz-'+t.slot+'.png',imageId,gid,store);
  const p=ps[t.slot];f.slot=t.slot;
  f.dx=t.x-(ax+p.x-t.width/2);f.dy=t.y-(ay+p.bottom-t.height);
  state.frames.push(f);
 }
 return {state:I.validate(state,store),store,gid,src};
}
function equalVisible(a,b){
 assert.deepEqual([a.width,a.height],[b.width,b.height]);
 for(let i=0;i<a.data.length;i+=4){
  assert.equal(a.data[i+3],b.data[i+3], 'alpha '+(i/4));
  if(a.data[i+3])for(let j=0;j<3;j++)assert.equal(a.data[i+j],b.data[i+j],'color '+(i/4));
 }
}
test('adversarial damage split preserves original canvas for varied isometric grids',()=>{
 let count=0;
 for(let a=1;a<=6;a++)for(let b=1;b<=6;b++)for(const h of [16,32,48,64]){
   const order=count%2?'descending':'ascending'; count++;
   const f=make(a,b,h,order,count);
   const ref=DI.baseComposite(f.state,f.store,f.gid);
   const create=DI.createStage(f.state,f.store,f.gid,'mechanical',50,'Ruin');
   const image=C.image(ref.image.width,ref.image.height,new Uint8Array(ref.image.data));
   const added=DI.withCandidate(create.state,create.store,create.stageId,image);
   try{
    const applied=DI.applyCandidate(added.state,added.store,create.stageId);
    const back=DI.baseComposite(applied.state,applied.store,create.sceneId);
    equalVisible(ref.image,back.image);
    assert.equal(back.layout.top,ref.layout.top);
    assert.equal(back.layout.left,ref.layout.left);
    assert.equal(back.layout.width,ref.layout.width);
    assert.equal(back.layout.height,ref.layout.height);
   }catch(e){throw new Error('GRID '+a+'x'+b+' height '+h+' order '+order+' source '+ref.image.width+'x'+ref.image.height+' => '+e.message);}
 }
});
