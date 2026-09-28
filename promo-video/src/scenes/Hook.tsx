import {AbsoluteFill,CanvasImage,interpolate,staticFile,useCurrentFrame} from "remotion";
import {Backdrop,Header,Footer,Reveal,clamp,C} from "../ui";
export const Hook=()=>{
const f=useCurrentFrame();
return <AbsoluteFill className="video"><Backdrop/><Header index={1} label="READ THE LABEL"/>
<Reveal style={{position:"absolute",left:112,top:248}}>
<div className="eyebrow" style={{marginBottom:27}}>选一份零食之前</div>
<div style={{fontSize:142,fontWeight:700,lineHeight:1.19,letterSpacing:-5}}>「高蛋白」<br/><span style={{color:C.mint}}>就适合你吗？</span></div>
<div style={{marginTop:42,fontSize:39,color:C.muted}}>答案，藏在标签里。</div>
</Reveal>
<Reveal delay={10} style={{position:"absolute",left:1110,top:208,rotate:interpolate(f,[0,180],[5,0],clamp)+"deg"}}>
<div style={{width:650,height:650,background:C.cream,padding:18,borderRadius:20,boxShadow:"0 40px 80px #0006",position:"relative",overflow:"hidden"}}>
<CanvasImage src={staticFile("sample-label.jpg")} style={{width:"100%",height:"100%",objectFit:"contain"}}/>
<div style={{position:"absolute",left:45,top:55,width:315,height:80,border:"3px solid "+C.mint,boxShadow:"0 0 0 999px #082b1620"}}/>
<div style={{position:"absolute",left:0,right:0,height:3,top:interpolate(f,[25,155],[150,620],clamp),background:C.mint,boxShadow:"0 -8px 40px "+C.mint}}/>
</div><div style={{fontSize:23,textAlign:"right",marginTop:20,color:C.muted}}>仓库合成标签 · 演示样例</div>
</Reveal><Footer index={1}/></AbsoluteFill>
};