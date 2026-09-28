import "./index.css";
import {Composition,Folder} from "remotion";
import {Promo} from "./Composition";
import {Hook} from "./scenes/Hook";
import {Brand} from "./scenes/Brand";
import {Input} from "./scenes/Input";
import {Numbers} from "./scenes/Numbers";
import {Evidence} from "./scenes/Evidence";
import {Review} from "./scenes/Review";
import {CTA} from "./scenes/CTA";
const specs=[["Hook",Hook,180],["Brand",Brand,180],["Input",Input,330],["Numbers",Numbers,360],["Evidence",Evidence,360],["Review",Review,180],["CTA",CTA,210]] as const;
export const RemotionRoot=()=> <>
<Composition id="IngredientRadarPromo" component={Promo} durationInFrames={1800} fps={30} width={1920} height={1080}/>
<Folder name="Scenes">{specs.map(([id,component,durationInFrames])=><Composition key={id} id={id} component={component} durationInFrames={durationInFrames} fps={30} width={1920} height={1080}/>)}</Folder>
</>;