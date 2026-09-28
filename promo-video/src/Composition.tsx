import {AbsoluteFill,Series,staticFile,useCurrentFrame} from "remotion";
import {Audio} from "@remotion/media";
import {Hook} from "./scenes/Hook";
import {Brand} from "./scenes/Brand";
import {Input} from "./scenes/Input";
import {Numbers} from "./scenes/Numbers";
import {Evidence} from "./scenes/Evidence";
import {Review} from "./scenes/Review";
import {CTA} from "./scenes/CTA";
import captions from "./captions.json";
const Captions=()=>{const f=useCurrentFrame();const cap=captions.find(c=>f>=c.start*30&&f<c.end*30);return cap?<div style={{position:"absolute",left:80,right:80,bottom:75,display:"flex",justifyContent:"center",pointerEvents:"none"}}><div style={{background:"#04160FDD",color:"#F4F6ED",padding:"9px 27px",borderRadius:9,fontSize:36,fontWeight:500,lineHeight:1.5,whiteSpace:"nowrap"}}>{cap.text}</div></div>:null;};
export const Promo=()=> <AbsoluteFill className="video">
<Series>
<Series.Sequence durationInFrames={180} name="高蛋白就适合你吗"><Hook/></Series.Sequence>
<Series.Sequence durationInFrames={180} name="成分雷达亮相"><Brand/></Series.Sequence>
<Series.Sequence durationInFrames={330} name="操作一：提供标签目标忌口"><Input/></Series.Sequence>
<Series.Sequence durationInFrames={360} name="操作二：每份营养"><Numbers/></Series.Sequence>
<Series.Sequence durationInFrames={360} name="操作三：回看证据"><Evidence/></Series.Sequence>
<Series.Sequence durationInFrames={180} name="不确定字段复核"><Review/></Series.Sequence>
<Series.Sequence durationInFrames={210} name="GitHub项目入口"><CTA/></Series.Sequence>
</Series>
<Audio src={staticFile("soundtrack.wav")} volume={1}/>
<Captions/>
</AbsoluteFill>;