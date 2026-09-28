import path from "node:path";
import {bundle} from "@remotion/bundler";
import {openBrowser,selectComposition,renderStill} from "@remotion/renderer";
const serveUrl=await bundle({entryPoint:path.resolve("src/index.ts")});
const browser=await openBrowser("chrome",{logLevel:"error"});
try {
const composition=await selectComposition({serveUrl,id:"IngredientRadarPromo",puppeteerInstance:browser});
for(const sec of [9,19,30,42,50,57]){
 await renderStill({serveUrl,composition,output:path.resolve("../output/promo-video/frame-"+String(sec).padStart(2,"0")+"s.png"),frame:sec*30,imageFormat:"png",puppeteerInstance:browser,logLevel:"error"});
 console.log("frame",sec);
}
} finally {await browser.close({silent:true});}
