'use strict';
const {test}=require('node:test');
const A=require('node:assert/strict');
const C=require('../src/core.js');
const I=require('../src/io.js');
const K=require('../src/codec.js');

function sourceGrid(a=3,b=3){
    const settings=C.scene({a,b,width:64,height:32,padding:0});
    const src=C.image(512,320),anchorX=256,anchorY=280;
    const map=C.partition(src,settings,anchorX,anchorY,true);
    for(let i=0;i<map.length;i++)if(map[i]>=0){
        const k=i*4;
        src.data[k]=(i%210)+20;
        src.data[k+1]=(i*11)%240;
        src.data[k+2]=132;
        src.data[k+3]=255;
    }
    return {settings,src,map,anchorX,anchorY};
}
function rgbaAt(tile,x,y){
    const xx=x-tile.x,yy=y-tile.y;
    if(xx<0||xx>=tile.width||yy<0||yy>=tile.height)return null;
    return Array.from(tile.image.data.subarray((yy*tile.width+xx)*4,(yy*tile.width+xx)*4+4));
}
function rgbaPixel(src,x,y){
    const k=(y*src.width+x)*4;
    return Array.from(src.data.subarray(k,k+4));
}
test('1px seam overlap duplicates opaque edge samples inside the existing 64px tile',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid();
    const old=C.split(src,map,settings,anchorX,anchorY);
    const newer=C.split(src,map,settings,anchorX,anchorY,null,
                        {overlap:1,rearShare:false});
    A.equal(newer.tiles.length,old.tiles.length);
    for(const tile of newer.tiles){
        A.equal(tile.width,64,'no tile may expand its real bitmap width');
        A.equal(tile.x,old.tiles[tile.slot].x,'same anchor geometry');
        A.equal(tile.y,old.tiles[tile.slot].y,'same vertical position');
    }
    let extra=0,seenOnlyInNew=0;
    for(let y=0;y<src.height;y++)for(let x=0;x<src.width;x++){
        const owner=map[y*src.width+x];
        if(owner<0)continue;
        const pixel=rgbaPixel(src,x,y);
        const oldCount=old.tiles.filter(t=>rgbaAt(t,x,y)?.[3]===255).length;
        const newCount=newer.tiles.filter(t=>rgbaAt(t,x,y)?.[3]===255).length;
        if(newCount>oldCount){
            extra+=newCount-oldCount;
            A.deepEqual(pixel,rgbaAt(newer.tiles.find(t=>t.slot!==owner&&rgbaAt(t,x,y)?.[3]===255),x,y));
            if(oldCount===1)seenOnlyInNew++;
        }
    }
    A.ok(extra>64, `Expected real 1px shared samples, got ${extra}`);
    A.ok(seenOnlyInNew>0);
    A.ok(newer.seamStats.edgeSamples>0);
});
test('rear row shares its half-width spatial overlap with adjacent front row',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid(5,5);
    const before=C.split(src,map,settings,anchorX,anchorY,null,
                         {overlap:1,rearShare:false});
    const after=C.split(src,map,settings,anchorX,anchorY,null,
                        {overlap:1,rearShare:true});
    const last=C.positions(settings).find(p=>p.diagonal===settings.a+settings.b-2);
    const rear=after.tiles[last.slot],old=before.tiles[last.slot];
    let shared=0;
    let fromLeft=0,fromRight=0;
    for(let y=0;y<src.height;y++)for(let x=rear.x;x<rear.x+rear.width;x++){
        const owner=map[y*src.width+x],pos=C.positions(settings)[owner];
        if(!pos||pos.diagonal!==last.diagonal-1)continue;
        if(rgbaAt(rear,x,y)?.[3]===255&&rgbaAt(old,x,y)?.[3]!==255){
            shared++;
            if(pos.x<last.x)fromLeft++;
            if(pos.x>last.x)fromRight++;
        }
    }
    A.ok(shared>50,`Expected substantial rear shared area, got ${shared}`);
    A.ok(fromLeft>0&&fromRight>0,
        'rear perimeter must share both adjoining half-tile footprints');
    A.equal(rear.width,64);
    A.ok(after.seamStats.rearSharedSamples>0);
});
test('opaque overlap preserves exact flattened RGBA when repainted in either order',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid();
    const result=C.split(src,map,settings,anchorX,anchorY,null,{overlap:1,rearShare:true});
    for(const order of [result.tiles,[...result.tiles].reverse()]){
        const out=C.image(src.width,src.height);
        for(const tile of order) C.blit(out,tile.image,tile.x,tile.y,true);
        A.deepEqual(Array.from(out.data),Array.from(src.data));
    }
});
test('fractional-alpha and meaningful masks are never double-composited',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid(2,2);
    const mask=C.image(src.width,src.height);
    let guarded=0;
    for(let y=0;y<src.height;y++)for(let x=0;x<src.width;x++){
        const i=y*src.width+x;
        if(map[i]<0)continue;
        if((x+y)%3===0)src.data[i*4+3]=128;
        else if((x+y)%5===0){mask.data[i*4]=27;guarded++;}
    }
    const tiles=C.split(src,map,settings,anchorX,anchorY,mask,{overlap:1,rearShare:true});
    const out=C.image(src.width,src.height);
    for(const tile of tiles.tiles)C.blit(out,tile.image,tile.x,tile.y,true);
    A.deepEqual(Array.from(out.data),Array.from(src.data));
    for(const tile of tiles.tiles){
        for(let y=Math.max(0,tile.y);y<Math.min(src.height,tile.y+tile.height);y++)
            for(let x=Math.max(0,tile.x);x<Math.min(src.width,tile.x+tile.width);x++){
                const i=y*src.width+x;
                if(map[i]===tile.slot||map[i]<0)continue;
                const pixel=rgbaAt(tile,x,y);
                if(src.data[i*4+3]!==255 || mask.data[i*4]!==0)
                    A.equal(pixel[3],0);
            }
    }
    A.ok(guarded>0);
});
test('legacy no-overlap mode remains byte-for-byte identical',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid();
    const old=C.split(src,map,settings,anchorX,anchorY);
    const plain=C.split(src,map,settings,anchorX,anchorY,null,{overlap:0,rearShare:false});
    for(let k=0;k<old.tiles.length;k++)A.deepEqual(
        Array.from(old.tiles[k].image.data),Array.from(plain.tiles[k].image.data));
});
test('1px overlap cannot quietly violate max 64px or accept nonsensical parameters',()=>{
    const {src,map,anchorX,anchorY}=sourceGrid();
    A.throws(()=>C.split(src,map,C.scene({a:3,b:3,width:66,height:32}),anchorX,anchorY,
                         null,{overlap:1,rearShare:true}),/64/);
    A.throws(()=>C.split(src,map,C.scene({a:3,b:3}),anchorX,anchorY,
                         null,{overlap:2}),/Überlappung/);
});



test('every shrinking rear diagonal shares its available half-width areas',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid(5,5);
    const positions=C.positions(settings);
    const after=C.split(src,map,settings,anchorX,anchorY,null,{overlap:1,rearShare:true});
    const last=settings.a+settings.b-2, first=Math.max(settings.a,settings.b);
    const coverage=new Map();
    for(const target of positions.filter(p=>p.diagonal>=first&&p.diagonal<=last)){
        const t=after.tiles[target.slot];
        for(let y=Math.max(0,t.y);y<Math.min(src.height,t.y+t.height);y++)
            for(let x=Math.max(0,t.x);x<Math.min(src.width,t.x+t.width);x++){
                const i=y*src.width+x,owner=map[i];
                if(owner<0||src.data[i*4+3]!==255)continue;
                const p=positions[owner];
                if(p.diagonal!==target.diagonal-1 ||
                   Math.abs(target.u-p.u)>1 || Math.abs(target.v-p.v)>1)continue;
                const actual=rgbaAt(t,x,y);
                const data=coverage.get(target.diagonal)||{expected:0,missing:0};
                data.expected++;
                if(!actual||actual[3]!==255)data.missing++;
                coverage.set(target.diagonal,data);
            }
    }
    A.deepEqual([...coverage.keys()].sort(),[5,6,7,8]);
    for(const [diagonal,datum] of coverage){
        A.ok(datum.expected>50,`rear row ${diagonal}: no eligible shared area`);
        A.equal(datum.missing,0,`rear row ${diagonal}: ${datum.missing} uncovered pixels`);
    }
});



test('meaningful material masks are not silently treated as safe overlaps',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid(3,3);
    const mask=C.image(src.width,src.height);
    let expected=0;
    for(let i=0;i<map.length;i++)
        if(map[i]>=0){mask.data[i*4+3]=255;expected++;}
    const analysis=C.splitAnalysis(src,map,settings,anchorX,anchorY,mask);
    A.equal(analysis.materialMaskPixels,expected);
    const output=C.split(src,map,settings,anchorX,anchorY,mask,
                         {overlap:1,rearShare:true});
    A.equal(output.seamStats.edgeSamples,0);
    A.equal(output.seamStats.rearSharedSamples,0);
    A.equal(output.seamStats.guardedMaterialMaskPixels,expected);
    for(const tile of output.tiles)A.equal(tile.width,64);
});


test('partially transparent inputs disclose that visible duplicates are guarded',()=>{
    const {settings,src,map,anchorX,anchorY}=sourceGrid(3,3);
    let expected=0;
    for(let i=0;i<map.length;i++)
        if(map[i]>=0){src.data[i*4+3]=128;expected++;}
    const a=C.splitAnalysis(src,map,settings,anchorX,anchorY);
    A.equal(a.partialAlphaPixels,expected);
    const output=C.split(src,map,settings,anchorX,anchorY,null,
                         {overlap:1,rearShare:true});
    A.equal(output.seamStats.guardedPartialAlphaPixels,expected);
    A.equal(output.seamStats.edgeSamples,0);
    A.equal(output.seamStats.rearSharedSamples,0);
    const restored=C.image(src.width,src.height);
    for(const tile of [...output.tiles].reverse())
        C.blit(restored,tile.image,tile.x,tile.y,true);
    A.deepEqual(Array.from(restored.data),Array.from(src.data));
});



test('rectangular and one-axis rear halves also share only existing tile regions',()=>{
    for(const [a,b] of [[1,5],[5,1],[2,3],[3,5]]){
        const {settings,src,map,anchorX,anchorY}=sourceGrid(a,b);
        const ps=C.positions(settings);
        const result=C.split(src,map,settings,anchorX,anchorY,null,
                             {overlap:1,rearShare:true});
        let candidates=0,missing=0;
        const rearStart=Math.ceil((a+b-1)/2);
        for(const p of ps.filter(p=>p.diagonal>=rearStart)){
            const tile=result.tiles[p.slot];
            for(let y=Math.max(0,tile.y);y<Math.min(src.height,tile.y+tile.height);y++)
                for(let x=Math.max(0,tile.x);x<Math.min(src.width,tile.x+tile.width);x++){
                    const i=y*src.width+x,owner=map[i];
                    if(owner<0||src.data[i*4+3]!==255)continue;
                    const source=ps[owner];
                    if(source.diagonal!==p.diagonal-1 ||
                       Math.abs(source.u-p.u)>1||Math.abs(source.v-p.v)>1)continue;
                    candidates++;
                    const sampled=rgbaAt(tile,x,y);
                    if(!sampled||sampled[3]!==255)missing++;
                }
        }
        A.ok(candidates>100,`no rear sample candidates for ${a}x${b}`);
        A.equal(missing,0,`rear gap in ${a}x${b} grid`);
        for(const tile of result.tiles)A.equal(tile.width,64);
    }
});
