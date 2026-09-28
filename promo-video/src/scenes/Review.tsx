import {AbsoluteFill,CanvasImage,staticFile} from "remotion";
import {Backdrop,Header,Footer,Reveal,SectionTitle,C} from "../ui";
export const Review=()=> <AbsoluteFill className="video"><Backdrop light/><Header index={6} label="HUMAN REVIEW" light/><SectionTitle step="把不确定，明确告诉你" light>看不清，就提示复核。</SectionTitle>
<Reveal delay={9} style={{position:"absolute",left:112,top:355,width:650,height:490,borderRadius:22,overflow:"hidden",background:"#DDD"}}>
<CanvasImage src={staticFile("blurry-label.jpg")} style={{width:"100%",height:"100%",objectFit:"cover"}}/>
<div style={{position:"absolute",left:22,bottom:22,padding:"9px 16px",borderRadius:7,background:C.cream,color:C.ink,fontSize:24}}>仓库模糊样例</div>
</Reveal>
<div style={{position:"absolute",left:883,top:360,width:920,color:C.ink}}>
<Reveal delay={18}><div style={{display:"flex",alignItems:"center",justifyContent:"space-between",padding:"28px 0",borderBottom:"2px solid #C3D2BD",fontSize:40}}><span>不可辨字段</span><span style={{color:"#75866D",fontSize:36}}>待确认</span></div></Reveal>
<Reveal delay={42}><div style={{fontSize:61,fontWeight:600,marginTop:41}}>请复核原包装</div><div style={{fontSize:35,marginTop:22,color:"#64795D"}}>缺失与不确定信息，会被明确标注。</div></Reveal>
<Reveal delay={100}><div style={{marginTop:57,padding:"22px 27px",border:"1px solid #B9CDAE",borderRadius:15,fontSize:35}}>你的目标，由你决定。</div></Reveal>
</div><Footer index={6} light/></AbsoluteFill>;