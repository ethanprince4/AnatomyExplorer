"""Liver, gallbladder, extrahepatic bile ducts, pancreas and duodenum: one gross specimen seen from the front.

Unlike the other models this is not a block of tissue but a dissection at life size (1 unit = 10 cm): the liver sits
in its natural position over the gallbladder, the portal triad, the pancreas and the C-loop of the duodenum, whose
descending part is opened from the front to show the major and minor papillae. The liver is the only thing that
moves when the layers are separated - it lifts straight up off the porta hepatis, the gallbladder and the ducts - and
the parenchyma of the liver, pancreas and duodenum fades with the tissue-opacity slider, so the hepatic veins, the
intrahepatic portal and biliary branches and the pancreatic ducts can be followed through the organs.

Axes: x = the patient's left, y = superior, z = anterior; the origin is in the midline at the level of L1.

Every organ is a signed-distance field. The liver is three ellipsoids smoothly merged and sliced by its visceral
surface, then carved by what presses on it (heart, stomach, kidney, duodenum) and by what runs through it (the
inferior vena cava, the fissures, the porta hepatis and the gallbladder fossa); its lobes are cut out of that one
field by the lines of the H on the visceral surface, so they fit together exactly. Hollow structures (the pylorus,
duodenum and jejunum) are built in tube coordinates - arc length, distance and angle round a centreline - which lets
the wall, the circular folds, the window in the second part and the papillae all be written as simple formulas.
"""
import math

import numpy as np
from scipy.spatial import cKDTree

from .geometry import Mesh, frames, smooth_path
from .kit import Volume, capsule, ellipsoid, mesh_part, round_cone, sdf_part, sphere
from .organic import Sweep, cell_profile, rmul, rsum, surf_noise, taper
from .sdf import smin

LIVER_RANK = 1.7          # the liver lifts off the porta hepatis when the parts are separated

# ----------------------------------------------------------------------------------------------- colours
C = {
    "right": "#8c3b2d", "left": "#80352a", "quadrate": "#97483a", "caudate": "#8f4333", "bare": "#5e3a31",
    "porta": "#d8c49c", "falciform": "#dcc8b8", "coronary": "#e3d4c3", "teres": "#efe3c6", "venosum": "#d9c9a9",
    "gb_fundus": "#4f8048", "gb_body": "#487a43", "gb_neck": "#41703d", "duct": "#a9c43a", "cbd": "#9dba30",
    "cystic": "#b1c948", "ampulla": "#bccd4f", "oddi": "#b25a4c",
    "head": "#e4ba8b", "uncinate": "#dcae7d", "neck": "#e9c294", "body": "#e3b98a", "tail": "#dbb183",
    "mpd": "#ece27a", "apd": "#e2d466",
    "d1": "#e2a58f", "d2": "#dd9d88", "d3": "#e0a18b", "d4": "#dc9b86", "mucosa": "#c9665d", "papilla": "#dc877c",
    "pylorus": "#d9998a", "jejunum": "#dea28f",
    "portal": "#6a57b3", "ivc": "#3160b5", "artery": "#c9312c",
}

# ----------------------------------------------------------------------------------------------- descriptions
DESC = {
    "right": "Right lobe of the liver: the largest lobe, about five sixths of the liver's bulk, filling the right "
             "hypochondrium under the right dome of the diaphragm. Anteriorly it is separated from the left lobe by "
             "the attachment of the falciform ligament; on the visceral surface it lies to the right of the "
             "gallbladder fossa and the groove for the inferior vena cava. Its visceral surface carries impressions "
             "for the right colic flexure, the right kidney and suprarenal gland and the duodenum. Functionally the "
             "liver is divided differently: Cantlie's line (gallbladder fossa to IVC, followed by the middle "
             "hepatic vein) splits it into right and left 'hemilivers' of roughly equal size, each with its own "
             "portal vein, hepatic artery and bile duct - the basis of the eight Couinaud segments and of "
             "hepatectomy. The liver is the largest gland (~1.5 kg): it stores glycogen, makes plasma proteins "
             "(albumin, clotting factors), detoxifies drugs and ammonia and secretes ~600 mL of bile a day.",
    "left": "Left lobe of the liver: the thinner, flattened lobe extending into the epigastrium and left "
            "hypochondrium, to the left of the falciform ligament and of the fissures for the ligamentum teres and "
            "ligamentum venosum. Its visceral surface bears the gastric impression and the omental tuberosity, "
            "which lies against the lesser omentum; its superior surface carries the shallow cardiac impression. "
            "It is anchored to the diaphragm by the left triangular ligament. The anatomical left lobe corresponds to "
            "Couinaud segments II and III (the left lateral section), the usual graft in living-donor liver "
            "transplantation for a child.",
    "quadrate": "Quadrate lobe: the rectangular area of the visceral surface between the gallbladder fossa (right), "
                "the fissure for the ligamentum teres (left), the porta hepatis (behind) and the inferior border "
                "(in front). Anatomically part of the right lobe but functionally part of the left liver (Couinaud "
                "segment IVb), because it is supplied by the left branches of the portal vein and hepatic artery and "
                "drained by the left hepatic duct. It rests on the pylorus and the first part of the duodenum.",
    "caudate": "Caudate lobe (with the caudate and papillary processes): the lobe on the posterior surface between "
               "the groove for the inferior vena cava (right) and the fissure for the ligamentum venosum (left), "
               "above and behind the porta hepatis. The caudate process joins it to the right lobe between the IVC "
               "and the porta; the papillary process bulges down towards the lesser sac. Couinaud segment I: it "
               "receives portal and arterial branches from both sides and drains by several short veins straight "
               "into the IVC - which is why it is spared and enlarges in Budd-Chiari syndrome (hepatic vein "
               "thrombosis), while the rest of the liver congests.",
    "bare": "Bare area of the liver: a large triangular area on the posterior surface of the right lobe that has no "
            "peritoneal covering and lies directly against the diaphragm, held by loose areolar tissue. It is "
            "outlined by the superior and inferior layers of the coronary ligament, which meet laterally at the "
            "right triangular ligament; the groove for the IVC is its base. Because it is extraperitoneal, "
            "infection can spread from here to the thorax (subphrenic abscess) and lymph drains through the "
            "diaphragm to mediastinal nodes; small veins here form a portosystemic anastomosis with phrenic veins.",
    "porta": "Porta hepatis (hilum of the liver): the transverse fissure, about 5 cm long, on the visceral surface "
             "between the quadrate lobe in front and the caudate lobe behind - the crossbar of the H formed by the "
             "fissures and fossae of the visceral surface. The hepatic portal vein and the hepatic artery proper "
             "enter here and the right and left hepatic ducts leave, together with lymphatics and the hepatic nerve "
             "plexus; the ducts lie in front, the arteries in the middle and the portal vein behind. The layers of "
             "the lesser omentum (hepatoduodenal ligament) attach to its margins, and the connective tissue sheath "
             "shown here is the hilar plate, a condensation of the liver capsule (Glisson) that surrounds the "
             "portal triad structures as they enter.",
    "falciform": "Falciform ligament: a sickle-shaped double fold of peritoneum attaching the anterior and superior "
                 "surfaces of the liver to the diaphragm and the anterior abdominal wall down to the umbilicus. It "
                 "marks the division between the anatomical right and left lobes on the diaphragmatic surface. Its "
                 "free lower border contains the round ligament (ligamentum teres) and the small paraumbilical "
                 "veins; superiorly its two layers separate - the right joins the superior layer of the coronary "
                 "ligament, the left the anterior layer of the left triangular ligament. It is a ventral mesentery "
                 "derivative and is cut here where it met the body wall.",
    "teres": "Round ligament of the liver (ligamentum teres hepatis): the fibrous remnant of the left umbilical "
             "vein, which in the fetus carried oxygenated blood from the placenta to the left branch of the portal "
             "vein and on through the ductus venosus. It runs in the free edge of the falciform ligament from the "
             "umbilicus to the notch in the inferior border, then in the fissure for the ligamentum teres to the "
             "left branch of the portal vein. In portal hypertension the paraumbilical veins that run with it "
             "reopen and carry portal blood to the veins of the abdominal wall around the umbilicus (caput "
             "medusae); the ligament can also be recanalised for access to the portal system.",
    "venosum": "Ligamentum venosum: the fibrous remnant of the ductus venosus, which in the fetus shunted "
               "placental blood from the left branch of the portal vein past the liver sinusoids into the inferior "
               "vena cava. It lies deep in the fissure for the ligamentum venosum, between the caudate and left "
               "lobes, and the lesser omentum attaches along the fissure. The ductus closes within days of birth; "
               "failure of closure is a congenital portosystemic shunt.",
    "coronary": "Coronary ligament: the peritoneal reflection from the diaphragm onto the posterior surface of the "
                "right lobe, in two layers that enclose the bare area. The superior layer continues from the right "
                "layer of the falciform ligament; the inferior layer reflects onto the right kidney and suprarenal "
                "gland (hepatorenal ligament). The two layers meet laterally as the right triangular ligament. "
                "Shown cut where the peritoneum left the liver for the diaphragm.",
    "rtri": "Right triangular ligament: the short lateral fold where the superior and inferior layers of the "
            "coronary ligament meet at the apex of the bare area, attaching the right lobe to the diaphragm.",
    "ltri": "Left triangular ligament: a double fold of peritoneum attaching the superior surface of the left lobe "
            "to the diaphragm. Its anterior layer is continuous with the left layer of the falciform ligament, its "
            "posterior layer with the lesser omentum; its free left end often contains a fibrous remnant of liver "
            "tissue (appendix fibrosa hepatis). It is divided to mobilise the left lobe at operation.",
    "gb_fundus": "Fundus of the gallbladder: the rounded blind end that projects beyond the inferior border of the "
                 "liver and touches the anterior abdominal wall at the tip of the ninth costal cartilage, where the "
                 "right midclavicular line meets the costal margin. Here an inflamed gallbladder is felt: pressure "
                 "during deep inspiration stops the breath with pain (Murphy's sign). A fundus folded over on itself "
                 "is the benign 'Phrygian cap' variant.",
    "gb_body": "Body of the gallbladder: the main part of the pear-shaped sac (7-10 cm long, ~50 mL), lying in the "
               "gallbladder fossa on the visceral surface of the liver, covered by peritoneum on its free surface "
               "and resting on the transverse colon and the first and second parts of the duodenum - through "
               "which a large gallstone can erode (cholecystoenteric fistula, gallstone ileus). The gallbladder "
               "stores bile and concentrates it 5-10 times by absorbing salt and water across its simple columnar "
               "epithelium; cholecystokinin, released by fat in the duodenum, contracts it.",
    "gb_neck": "Neck of the gallbladder: the narrow, S-shaped end pointing towards the porta hepatis. Its mucosa "
               "forms a spiral fold continuous with that of the cystic duct, and a pouch on its inferior wall "
               "(Hartmann's pouch) is where gallstones commonly lodge, blocking the outflow: biliary colic, and "
               "acute cholecystitis if the obstruction persists. A stone impacted here can compress the common "
               "hepatic duct and cause jaundice (Mirizzi syndrome).",
    "cystic": "Cystic duct: 3-4 cm long, joining the neck of the gallbladder to the common hepatic duct, usually on "
              "its right side, to form the (common) bile duct. Its mucosa forms a spiral fold (valve of Heister) "
              "that keeps it open. With the common hepatic duct and the inferior surface of the liver it bounds the "
              "cystohepatic triangle (Calot's triangle), which contains the cystic artery and the cystic lymph node; "
              "the 'critical view of safety' in laparoscopic cholecystectomy clears this triangle so that only two "
              "structures - cystic duct and cystic artery - are seen entering the gallbladder before they are "
              "clipped, protecting the bile duct from injury.",
    "rhd": "Right hepatic duct: drains bile from the right liver (Couinaud segments V-VIII) through its anterior and "
           "posterior sectoral ducts, emerging from the porta hepatis to join the left hepatic duct. It is short "
           "(~1 cm) and runs almost vertically. Bile flows from hepatocytes into canaliculi, then canals of Hering, "
           "interlobular ducts in the portal triads, and so to the hepatic ducts - opposite to the flow of blood.",
    "lhd": "Left hepatic duct: drains the left liver (segments II-IV) and the left part of the caudate lobe. Longer "
           "(~2 cm) and more horizontal than the right, it runs along the base of the quadrate lobe to the "
           "confluence at the right end of the porta hepatis. A tumour of the confluence (hilar "
           "cholangiocarcinoma, Klatskin tumour) obstructs both ducts and causes painless jaundice.",
    "chd": "Common hepatic duct: formed at the porta hepatis by the union of the right and left hepatic ducts; about "
           "3 cm long, it descends in the free edge of the lesser omentum (hepatoduodenal ligament), to the right "
           "of the hepatic artery proper and in front of the portal vein, until the cystic duct joins it. It forms "
           "the left border of Calot's triangle; misidentifying it as the cystic duct is the classic cause of bile "
           "duct injury at cholecystectomy.",
    "cbd": "Common bile duct (bile duct): 6-8 cm long and up to ~6 mm wide, formed by the cystic and common hepatic "
           "ducts. It has four parts: supraduodenal (in the free edge of the lesser omentum, right-anterior to the "
           "portal vein, with the hepatic artery on its left - the portal triad felt in the Pringle manoeuvre), "
           "retroduodenal (behind the first part of the duodenum), pancreatic (in a groove or tunnel in the back of "
           "the pancreatic head, in front of the IVC) and intraduodenal (oblique through the wall of the second "
           "part). It ends by joining the main pancreatic duct in the hepatopancreatic ampulla. A stone in the "
           "duct (choledocholithiasis) or a carcinoma of the pancreatic head blocks it: obstructive jaundice with "
           "pale stools, dark urine and itching.",
    "ampulla": "Hepatopancreatic ampulla (ampulla of Vater): the short dilatation within the wall of the second part "
               "of the duodenum where the bile duct and the main pancreatic duct unite, opening at the summit of "
               "the major duodenal papilla. Because bile and pancreatic juice share this common channel, a small "
               "gallstone impacted here can let bile reflux into the pancreatic duct and obstruct pancreatic "
               "outflow - gallstone pancreatitis - as well as blocking bile (jaundice). Ampullary carcinoma presents "
               "early with painless jaundice.",
    "oddi": "Hepatopancreatic sphincter (sphincter of Oddi): a complex of smooth muscle around the ampulla and the "
            "terminal bile and pancreatic ducts, independent of the duodenal muscle, with its own choledochal "
            "sphincter (on the bile duct - keeps it closed between meals so bile backs up the cystic duct into the "
            "gallbladder) and pancreatic sphincter. Cholecystokinin relaxes it as the gallbladder contracts; "
            "opioids (morphine) contract it. Endoscopic sphincterotomy (at ERCP) cuts it to extract bile duct "
            "stones; sphincter dysfunction causes biliary-type pain.",
    "major_pap": "Major duodenal papilla: the nipple-like mound on the posteromedial wall of the descending "
                 "(second) part of the duodenum, about 7-10 cm from the pylorus, where the hepatopancreatic ampulla "
                 "opens. A hooding fold lies over it and a longitudinal fold runs down from it - the landmarks used "
                 "to cannulate it at ERCP. Bile and pancreatic juice enter the duodenum here: bile salts emulsify "
                 "fat into small droplets, giving pancreatic lipase a much larger surface to act on.",
    "minor_pap": "Minor duodenal papilla: a smaller mound about 2 cm above and slightly in front of the major "
                 "papilla, where the accessory pancreatic duct (of Santorini) opens. In pancreas divisum (~7% of "
                 "people; the dorsal and ventral pancreatic ducts fail to fuse) most of the pancreas drains through "
                 "this small opening, which can cause recurrent pancreatitis.",
    "head": "Head of the pancreas: the thickest part, lying in the C-shaped concavity of the duodenum, in front of "
            "the inferior vena cava and the left renal vein, at the level of L2. The bile duct runs in a groove or "
            "tunnel on its posterior surface, and the gastroduodenal and pancreaticoduodenal arteries on and around "
            "it. About 70% of pancreatic cancers arise here: compression of the bile duct gives painless "
            "obstructive jaundice with a palpable, non-tender gallbladder (Courvoisier's law); treatment is "
            "pancreaticoduodenectomy (Whipple operation). The pancreas is an exocrine gland (acini secrete "
            "digestive enzymes, duct cells secrete bicarbonate to neutralise acid chyme) and an endocrine gland "
            "(islets secrete insulin, glucagon and somatostatin).",
    "uncinate": "Uncinate process: the hook-shaped extension of the lower part of the head that curves to the left "
                "behind the superior mesenteric vein (and often the artery), in front of the aorta and IVC. It "
                "develops from the ventral pancreatic bud, which rotates round the duodenum with the bile duct and "
                "fuses with the dorsal bud. A tumour here can involve the superior mesenteric vessels early.",
    "neck": "Neck of the pancreas: the short (~2 cm), narrow part joining the head to the body, lying in front of "
            "the portal vein, which is formed behind it by the union of the superior mesenteric and splenic veins. "
            "The pylorus lies in front of it. Its posterior surface is grooved by the portal vein, and surgeons "
            "tunnel behind the neck along this plane during pancreaticoduodenectomy.",
    "body": "Body of the pancreas: runs to the left and slightly upward across the aorta, the origin of the superior "
            "mesenteric artery, the left crus of the diaphragm, the left suprarenal gland and the left kidney, "
            "forming the bed of the stomach behind the lesser sac. The splenic artery runs a tortuous course along "
            "its upper border and the splenic vein lies in a groove on its back. Because it lies across the "
            "vertebral column it is crushed in blunt upper-abdominal trauma (e.g. against a bicycle handlebar), "
            "causing traumatic pancreatitis or duct transection; a pseudocyst can form in the lesser sac.",
    "tail": "Tail of the pancreas: the narrow, mobile left end, lying in the splenorenal ligament with the splenic "
            "vessels and reaching the hilum of the spleen - it can be injured during splenectomy, causing a "
            "pancreatic fistula. Islets are most numerous in the tail.",
    "mpd": "Main pancreatic duct (duct of Wirsung): runs from the tail through the body and neck, turning downward "
           "in the head to join the bile duct in the hepatopancreatic ampulla (major papilla). It is about 3 mm "
           "wide in the head and receives short tributaries along its length in a herringbone pattern. It carries "
           "~1.5 L/day of alkaline, enzyme-rich pancreatic juice. Obstruction (a stone at the ampulla, a tumour, "
           "chronic pancreatitis strictures) raises pressure in the duct and activates enzymes within the gland "
           "- pancreatitis.",
    "apd": "Accessory pancreatic duct (duct of Santorini): drains the upper anterior part of the head, running from "
           "the main duct to the minor duodenal papilla. It is the persisting proximal part of the duct of the "
           "dorsal pancreatic bud, and it often communicates with the main duct, so it can act as a bypass when "
           "the main duct is blocked.",
    "d1": "Superior (first) part of the duodenum: about 5 cm long, running from the pylorus to the right, upward and "
          "backward at L1 to the superior duodenal flexure beside the neck of the gallbladder. Its first 2 cm - the "
          "duodenal cap or ampulla - is mobile, intraperitoneal and smooth-walled inside; the rest is "
          "retroperitoneal. The bile duct, gastroduodenal artery and portal vein pass behind it. Most duodenal "
          "ulcers occur in the cap: a posterior ulcer can erode the gastroduodenal artery (major bleeding), an "
          "anterior one can perforate into the peritoneal cavity. The duodenum receives acid chyme from the "
          "stomach and neutralises it with bile, pancreatic bicarbonate and the alkaline mucus of its Brunner "
          "glands.",
    "d2": "Descending (second) part of the duodenum: 7-10 cm long, running down on the right of L1-L3 in front of "
          "the hilum of the right kidney, wrapped round the head of the pancreas. It is opened here from the front "
          "to show its mucosa with circular folds and, on its posteromedial wall, the major duodenal papilla (bile "
          "and main pancreatic ducts) and the minor papilla above it (accessory pancreatic duct). The transverse "
          "colon crosses in front of it. It marks the embryological junction of foregut and midgut, at the "
          "papilla, and its blood supply changes there from the coeliac trunk to the superior mesenteric artery.",
    "d3": "Horizontal (third) part of the duodenum: 6-8 cm long, crossing from right to left at L3 in front of the "
          "IVC and aorta and behind the superior mesenteric artery and vein. It can be compressed in the angle "
          "between the aorta and the superior mesenteric artery (SMA syndrome), typically after rapid weight loss, "
          "causing high intestinal obstruction.",
    "d4": "Ascending (fourth) part of the duodenum: about 2.5 cm long, rising on the left of the aorta to the "
          "duodenojejunal flexure at L2, which is suspended by the suspensory muscle of the duodenum (ligament of "
          "Treitz) - the landmark dividing upper from lower gastrointestinal bleeding and the point from which "
          "the small bowel is run at laparotomy. Malrotation places the flexure to the right of the midline.",
    "mucosa": "Duodenal mucosa with circular folds (plicae circulares): permanent transverse folds of mucosa and "
              "submucosa, crescent-shaped, that begin in the second part and become taller and more crowded in "
              "the jejunum; with villi and microvilli they multiply the absorptive surface. The first part (the "
              "cap) is smooth. Histology: simple columnar epithelium with goblet cells on villi, and duodenal "
              "(Brunner) glands in the submucosa secreting alkaline mucus. A longitudinal fold runs down from the "
              "major papilla.",
    "pylorus": "Pylorus and pyloric antrum of the stomach (cut): the pyloric canal ends at the pyloric sphincter, a "
               "thickening of the circular smooth muscle that meters chyme into the duodenum and prevents "
               "duodenogastric reflux. Its position is the transpyloric plane (L1), a key abdominal landmark. "
               "Hypertrophy of this muscle in infants (pyloric stenosis) causes projectile vomiting and a "
               "palpable 'olive'.",
    "jejunum": "Jejunum (cut): the small intestine continues from the duodenojejunal flexure as the jejunum, now "
               "suspended on the mesentery; it has thicker walls, taller and denser circular folds and fewer "
               "arterial arcades than the ileum.",
    "portal": "Hepatic portal vein: about 8 cm long, formed behind the neck of the pancreas at L1-L2 by the union "
              "of the superior mesenteric and splenic veins. It ascends behind the first part of the duodenum and "
              "then in the free edge of the lesser omentum, behind the bile duct and hepatic artery (forming the "
              "anterior boundary of the omental foramen), and divides at the porta hepatis into right and left "
              "branches that ramify with the arteries and ducts to the portal triads. It brings ~75% of the liver's "
              "blood (nutrient-rich, low-oxygen blood from the gut, spleen, pancreas and gallbladder) - hepatic "
              "artery and portal blood mix in the sinusoids and drain to the central veins. Portal hypertension "
              "(usually cirrhosis) opens portosystemic anastomoses: oesophageal and gastric varices (left gastric "
              "to oesophageal veins), rectal varices, caput medusae (paraumbilical veins) and retroperitoneal "
              "collaterals, with splenomegaly and ascites.",
    "splenic_v": "Splenic vein: drains the spleen, running from the splenic hilum to the right in a groove on the "
                 "posterior surface of the tail and body of the pancreas, receiving short pancreatic veins, the "
                 "short gastric and left gastro-omental veins and usually the inferior mesenteric vein, and joining "
                 "the superior mesenteric vein behind the neck of the pancreas. Splenic vein thrombosis (from "
                 "pancreatitis or pancreatic cancer) causes isolated gastric varices ('left-sided' portal "
                 "hypertension).",
    "smv": "Superior mesenteric vein: drains the small intestine, caecum, ascending and transverse colon, head of the "
           "pancreas and part of the stomach. It ascends in the root of the mesentery to the right of the superior "
           "mesenteric artery, crosses in front of the third part of the duodenum and the uncinate process, and "
           "joins the splenic vein behind the neck of the pancreas to form the portal vein.",
    "imv": "Inferior mesenteric vein: drains the left colon, sigmoid and upper rectum; it ascends to the left of the "
           "duodenojejunal flexure and ends behind the body of the pancreas, usually in the splenic vein (or in "
           "the superior mesenteric vein or the confluence). Its rectal tributaries form a portosystemic "
           "anastomosis with the middle and inferior rectal veins.",
    "ivc": "Inferior vena cava: returns blood from the lower body, ascending on the right of the vertebral column, "
           "behind the head of the pancreas, the bile duct and the portal vein (forming the posterior boundary of "
           "the omental foramen), and then in a deep groove on the bare area of the liver, where it receives the "
           "hepatic veins before piercing the central tendon of the diaphragm at T8 to enter the right atrium.",
    "hv": "Hepatic veins (right, middle and left): short, valveless veins that run between the liver's portal "
          "territories - the middle vein in Cantlie's plane between the functional right and left liver - "
          "collecting blood from the central veins of the lobules, and open into the inferior vena cava just below "
          "the diaphragm, with extra small veins from the caudate lobe. They are the liver's only venous outflow, "
          "embedded in the parenchyma without surrounding connective tissue. Their obstruction (Budd-Chiari "
          "syndrome) causes painful hepatomegaly and ascites; in right heart failure back-pressure through them "
          "gives the 'nutmeg liver'.",
    "aorta": "Abdominal aorta: enters the abdomen through the aortic hiatus at T12 and descends on the left of the "
             "vertebral bodies, giving the coeliac trunk (T12) and the superior mesenteric artery (L1) - the "
             "arteries of the foregut and midgut - behind the pancreas.",
    "coeliac": "Coeliac trunk: the artery of the foregut, a 1-2 cm trunk arising from the front of the aorta at T12 "
               "just above the pancreas, dividing into the left gastric, splenic and common hepatic arteries. It "
               "supplies the liver, gallbladder, stomach, spleen, the upper duodenum and much of the pancreas.",
    "lga": "Left gastric artery (cut): the smallest branch of the coeliac trunk, running up to the cardia and then "
           "along the lesser curvature of the stomach; it gives oesophageal branches, and its vein (the left "
           "gastric or coronary vein) is the route of oesophageal varices in portal hypertension.",
    "splenic_a": "Splenic artery: the largest branch of the coeliac trunk, running a tortuous course to the left "
                 "along the upper border of the pancreas, supplying the pancreatic body and tail (dorsal and great "
                 "pancreatic arteries) and giving the short gastric and left gastro-omental arteries before "
                 "entering the splenic hilum. A common site of visceral aneurysm and of erosion by pancreatic "
                 "pseudocysts.",
    "cha": "Common hepatic artery: runs to the right from the coeliac trunk along the upper border of the head of "
           "the pancreas, behind the lesser sac, and divides into the gastroduodenal artery and the hepatic artery "
           "proper. The liver gets ~25% of its blood but about half of its oxygen from the hepatic artery.",
    "pha": "Hepatic artery proper: continues from the common hepatic artery after the gastroduodenal branch, gives "
           "the right gastric artery, and ascends in the hepatoduodenal ligament, to the left of the bile duct and "
           "in front of the portal vein, dividing near the porta hepatis into right and left hepatic arteries. "
           "Compressing the free edge of the lesser omentum (Pringle manoeuvre) stops hepatic arterial and portal "
           "inflow during liver bleeding.",
    "rha": "Right hepatic artery: usually passes behind the common hepatic duct into Calot's triangle, where it "
           "gives the cystic artery, and enters the right liver. In ~15% of people it arises instead from the "
           "superior mesenteric artery (replaced right hepatic artery) and runs behind the portal vein - important "
           "in cholecystectomy and pancreatic surgery.",
    "lha": "Left hepatic artery: runs to the left along the porta hepatis to the left liver, giving a branch to the "
           "caudate lobe and often the middle hepatic artery to segment IV. It may arise from the left gastric "
           "artery (replaced left hepatic artery, ~10%).",
    "cystic_a": "Cystic artery: usually arises from the right hepatic artery in Calot's triangle and runs to the "
                "neck of the gallbladder, dividing into superficial and deep branches over its free and hepatic "
                "surfaces. It is an end artery: inflammation and distension of the gallbladder can compromise it, "
                "leading to gangrene and perforation in acute cholecystitis. It is clipped with the cystic duct at "
                "cholecystectomy.",
    "gda": "Gastroduodenal artery: arises from the common hepatic artery and descends behind the first part of the "
           "duodenum, dividing into the right gastro-omental and the superior pancreaticoduodenal arteries, which "
           "supply the pancreatic head and duodenum and anastomose with the inferior pancreaticoduodenal arteries "
           "from the SMA. A posterior duodenal ulcer erodes it, causing massive haematemesis or melaena.",
    "sma": "Superior mesenteric artery: the artery of the midgut, arising from the aorta at L1 about 1 cm below the "
           "coeliac trunk. It passes behind the neck of the pancreas and then in front of the uncinate process and "
           "the third part of the duodenum into the root of the mesentery, with the superior mesenteric vein on "
           "its right. Embolism to it causes acute mesenteric ischaemia - pain out of proportion to the "
           "examination.",
}


# ----------------------------------------------------------------------------------------------- helpers
def _smax(a, b, k):
    """Smooth maximum (intersection with a rounded edge of size k)."""
    return -smin(-a, -b, k)


def _max(*fields):
    """Intersection of broadcastable fields."""
    out = fields[0]
    for f in fields[1:]:
        out = np.maximum(out, f)
    return out


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _resample(path, spacing):
    path = np.asarray(path, float)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(int(arc[-1] / spacing) + 1, 3)
    s = np.linspace(0.0, arc[-1], n)
    return np.stack([np.interp(s, arc, path[:, c]) for c in range(3)], -1)


def _spline(ctrl, spacing=0.01):
    ctrl = np.asarray(ctrl, float)
    return _resample(smooth_path(ctrl, max(len(ctrl) * 30, 60)), spacing)


def _tube(ctrl, radius, n_theta=26, spacing=0.012, rough=0.03, seed=0):
    """A vessel or duct: a swept solid round a spline, radius a number or a profile along its length."""
    path = _spline(ctrl, spacing * 0.5)
    n_s = int(np.clip(len(path) // 2, 16, 420))
    sw = Sweep(path, n_theta, n_s)
    r = taper(radius) if isinstance(radius, (list, tuple)) else radius
    return sw.solid(rmul(r, rsum(1.0, surf_noise(rough, 1.2, 3.0 + sw.length * 4.0, seed))))


def _branches(trunk_end, tips, radius, seed=0):
    """Intrahepatic branches fanning out from the end of a trunk, each tapering to a point."""
    m = Mesh()
    a = np.asarray(trunk_end, float)
    for k, tip in enumerate(tips):
        tip = np.asarray(tip, float)
        mid = a + (tip - a) * 0.5 + np.array([0.0, 0.03, 0.0]) * ((k % 2) * 2 - 1)
        m.extend(_tube([a, mid, tip], [radius, radius * 0.7, radius * 0.25], 16, rough=0.05, seed=seed + k))
    return m


def _inside_liver(p, margin=0.05):
    """Rough test that points lie inside the liver (for placing intrahepatic branches)."""
    p = np.atleast_2d(np.asarray(p, float))
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    e = np.min([f(x, y, z) for f, _, _ in LIVER_BODY], axis=0)
    zp = -0.6 + 0.26 * np.exp(-((x + 0.1) / 0.38) ** 2)
    return (e < -margin) & (y > _yv(x, z) + margin) & (z > zp + margin)


# primary branch targets of the right and left portal pedicles (sectoral and segmental territories)
PEDICLE_TIPS = {
    "right": [(-0.62, 0.27, 0.42), (-0.8, 0.52, 0.26), (-0.9, 0.34, -0.2), (-0.7, 0.68, -0.2)],
    "left": [(0.42, 0.52, 0.26), (0.3, 0.46, 0.46), (0.7, 0.62, 0.14), (-0.13, 0.26, 0.47), (-0.1, 0.55, 0.32)],
}


def _pedicle_paths(side, root, seed):
    """Branching centrelines of one portal pedicle: primaries to fixed territories, each giving a few secondary
    branches that stay inside the liver. Returned as (path, relative starting calibre)."""
    rng = np.random.default_rng(seed)
    out = []
    a = np.asarray(root, float)
    for tip in PEDICLE_TIPS[side]:
        b = np.asarray(tip, float)
        mid = a + (b - a) * 0.45 + rng.normal(0.0, 0.025, 3)
        prim = _spline([a, mid, b], 0.01)
        out.append((prim, 1.0))
        for t in (0.4, 0.62, 0.84):
            i = int(t * (len(prim) - 1))
            p0 = prim[i]
            tan = prim[min(i + 1, len(prim) - 1)] - prim[max(i - 1, 0)]
            tan /= np.linalg.norm(tan)
            for _ in range(12):
                d = rng.normal(size=3)
                d -= tan * (d @ tan)
                d = d / np.linalg.norm(d) * 0.8 + tan * 0.45
                d /= np.linalg.norm(d)
                length = rng.uniform(0.11, 0.2) * (1.15 - 0.45 * t)
                end = p0 + d * length
                if _inside_liver(end)[0] and _inside_liver(p0 + d * length * 0.5)[0]:
                    bend = rng.normal(0.0, 0.012, 3)
                    out.append((_spline([p0, p0 + d * length * 0.5 + bend, end], 0.01), 0.55 * (1.0 - 0.45 * t)))
                    break
    return out


def _pedicle_mesh(paths, r0, off_root=(0.0, 0.0, 0.0), off_tip=(0.0, 0.0, 0.0), n_theta=16, seed=0):
    """One system of a pedicle (portal vein, hepatic duct or hepatic artery) following the shared centrelines,
    shifted a little so the three run side by side as they do in the portal canals."""
    m = Mesh()
    off_root, off_tip = np.asarray(off_root, float), np.asarray(off_tip, float)
    for k, (path, rel) in enumerate(paths):
        f = np.linspace(0.0, 1.0, len(path))[:, None]
        if rel >= 1.0:
            shift = off_root + (off_tip - off_root) * _smoothstep(f / 0.35)
        else:
            shift = np.broadcast_to(off_tip, path.shape)
        r = r0 * rel
        m.extend(_tube(path + shift, [r, r * 0.8, r * 0.55, r * 0.22], n_theta, spacing=0.01, rough=0.05,
                       seed=seed + k))
    return m


def _path_shapes(path, radii):
    """Round-cone segments along a sampled path (for carving grooves)."""
    path = np.asarray(path, float)
    radii = np.broadcast_to(np.asarray(radii, float), (len(path),))
    return [round_cone(path[i], path[i + 1], float(radii[i]), float(radii[i + 1])) for i in range(len(path) - 1)]


# ----------------------------------------------------------------------------------------------- the layout
# Liver: visceral surface height y_v(x, z) - the inferior border rises from right to left and the surface slopes
# up towards the back.
def _yv(x, z):
    x = np.asarray(x)
    cx = 0.27 + 0.11 * np.tanh(x / 0.2)
    lateral = -0.16 * _smoothstep((-0.5 - x) / 0.7) + 0.1 * _smoothstep((x - 0.3) / 0.6)
    return cx * x + lateral + 0.26 * (0.72 - z)


def _on_visceral(x, z, dy=0.0):
    return (x, float(_yv(x, z)) + dy, z)


IVC_CTRL = [(-0.28, -1.15, -0.30), (-0.265, -0.4, -0.32), (-0.255, 0.35, -0.33), (-0.24, 0.8, -0.32),
            (-0.2, 1.12, -0.27)]
IVC_R = 0.11
AORTA_CTRL = [(0.08, 0.38, -0.38), (0.08, -0.4, -0.36), (0.075, -1.15, -0.33)]
AORTA_R = 0.105

# gallbladder centreline, fundus -> neck, and its radii
GB_CTRL = [(-0.465, -0.1, 0.66), (-0.44, -0.07, 0.55), (-0.4, -0.03, 0.43), (-0.355, 0.015, 0.32),
           (-0.315, 0.045, 0.24), (-0.29, 0.075, 0.17), (-0.278, 0.075, 0.125)]
GB_R = [0.125, 0.125, 0.115, 0.095, 0.075, 0.052, 0.03]

# biliary tree
RHD_CTRL = [(-0.34, 0.25, 0.1), (-0.26, 0.22, 0.1), (-0.17, 0.2, 0.1)]
LHD_CTRL = [(0.04, 0.22, 0.14), (-0.05, 0.21, 0.12), (-0.17, 0.2, 0.1)]
CHD_CTRL = [(-0.17, 0.2, 0.1), (-0.185, 0.11, 0.1), (-0.2, 0.03, 0.09), (-0.211, -0.035, 0.082)]
CYSTIC_CTRL = [(-0.278, 0.075, 0.13), (-0.285, 0.03, 0.118), (-0.272, -0.02, 0.104), (-0.245, -0.045, 0.09),
               (-0.215, -0.04, 0.083)]
AMPULLA = np.array([-0.443, -0.505, -0.1])
CBD_CTRL = [(-0.211, -0.035, 0.082), (-0.218, -0.1, 0.065), (-0.23, -0.17, 0.035), (-0.255, -0.26, -0.03),
            (-0.31, -0.37, -0.09), (-0.37, -0.45, -0.117), (-0.415, -0.49, -0.114), tuple(AMPULLA)]
MPD_CTRL = [(0.93, 0.2, -0.16), (0.7, 0.08, -0.06), (0.45, -0.05, 0.045), (0.2, -0.16, 0.14), (0.0, -0.245, 0.2),
            (-0.13, -0.3, 0.14), (-0.22, -0.39, 0.05), (-0.31, -0.47, -0.04), (-0.39, -0.5, -0.09), tuple(AMPULLA)]
PAPILLA_APEX = AMPULLA + np.array([-0.018, -0.006, 0.014])
MINOR_PAP = np.array([-0.4, -0.36, -0.018])
MINOR_TIP = MINOR_PAP + np.array([-0.03, 0.0, 0.006])
APD_CTRL = [(-0.08, -0.28, 0.17), (-0.2, -0.31, 0.1), (-0.31, -0.345, 0.03), (-0.37, -0.36, -0.01),
            tuple(MINOR_PAP)]

# portal venous system
CONFLUENCE = (-0.01, -0.27, 0.115)
PV_CTRL = [CONFLUENCE, (-0.06, -0.12, 0.05), (-0.11, 0.03, 0.005), (-0.14, 0.14, 0.0), (-0.15, 0.19, 0.01)]
RPV_CTRL = [(-0.15, 0.19, 0.01), (-0.26, 0.2, 0.0), (-0.38, 0.23, 0.0)]
LPV_CTRL = [(-0.15, 0.19, 0.01), (-0.06, 0.2, 0.03), (0.03, 0.2, 0.07), (0.055, 0.2, 0.18), (0.055, 0.19, 0.3)]
SV_CTRL = [(1.0, 0.2, -0.25), (0.8, 0.12, -0.19), (0.62, 0.02, -0.11), (0.45, -0.08, -0.04), (0.2, -0.2, 0.05),
           CONFLUENCE]
SMV_CTRL = [(0.0, -1.12, 0.305), (-0.012, -0.95, 0.285), (-0.02, -0.7, 0.25), (-0.02, -0.45, 0.19), CONFLUENCE]
IMV_CTRL = [(0.5, -1.12, 0.02), (0.49, -0.8, -0.05), (0.42, -0.45, -0.07), (0.36, -0.2, -0.04), (0.35, -0.14, -0.005)]

# arteries
COELIAC_O = (0.08, 0.02, -0.28)
TRIFURC = (0.08, 0.03, -0.1)
CHA_CTRL = [TRIFURC, (-0.01, 0.0, -0.03), (-0.08, -0.03, 0.02), (-0.12, -0.05, 0.05)]
PHA_CTRL = [(-0.12, -0.05, 0.05), (-0.122, 0.04, 0.06), (-0.112, 0.13, 0.062), (-0.1, 0.18, 0.064)]
RHA_CTRL = [(-0.1, 0.18, 0.064), (-0.16, 0.195, 0.05), (-0.24, 0.205, 0.045), (-0.33, 0.22, 0.05)]
LHA_CTRL = [(-0.1, 0.18, 0.064), (-0.03, 0.2, 0.08), (0.04, 0.215, 0.1), (0.1, 0.26, 0.14)]
CYSTIC_A_CTRL = [(-0.24, 0.205, 0.045), (-0.275, 0.18, 0.09), (-0.3, 0.13, 0.15), (-0.335, 0.1, 0.23),
                 (-0.37, 0.08, 0.34)]
GDA_CTRL = [(-0.12, -0.05, 0.05), (-0.125, -0.14, 0.09), (-0.13, -0.25, 0.155), (-0.14, -0.38, 0.215),
            (-0.17, -0.47, 0.235)]
SPLENIC_A_CTRL = [TRIFURC, (0.2, 0.05, -0.12), (0.3, 0.1, -0.08), (0.42, 0.08, -0.12), (0.55, 0.14, -0.1),
                  (0.66, 0.13, -0.17), (0.78, 0.22, -0.18), (0.9, 0.24, -0.24), (1.02, 0.3, -0.27)]
LGA_CTRL = [TRIFURC, (0.12, 0.1, -0.08), (0.18, 0.22, -0.04), (0.2, 0.33, 0.0)]
SMA_CTRL = [(0.08, -0.1, -0.28), (0.09, -0.17, -0.08), (0.1, -0.32, 0.07), (0.105, -0.52, 0.17),
            (0.11, -0.76, 0.25), (0.12, -0.98, 0.3), (0.125, -1.12, 0.31)]

# duodenum centreline from the pyloric antrum to the start of the jejunum, with the landmarks between its parts
GUT_CTRL = [(0.27, -0.36, 0.5), (0.2, -0.33, 0.465), (0.1, -0.3, 0.42), (-0.08, -0.27, 0.37),
            (-0.28, -0.26, 0.26), (-0.43, -0.28, 0.12), (-0.515, -0.38, 0.01), (-0.535, -0.52, -0.01),
            (-0.52, -0.72, 0.0), (-0.45, -0.9, 0.02), (-0.25, -0.98, 0.04), (0.0, -0.99, 0.05),
            (0.18, -0.95, 0.03), (0.29, -0.82, 0.01), (0.32, -0.67, 0.03), (0.42, -0.64, 0.13),
            (0.52, -0.72, 0.21), (0.57, -0.86, 0.25)]
GUT_MARKS = {"pylorus": 2, "sup_flexure": 5, "inf_flexure": 9, "d3d4": 12, "dj": 14}


# ----------------------------------------------------------------------------------------------- tube coordinates
class _Axis:
    """A dense centreline with arc length and parallel-transport frames, turning grid points into tube
    coordinates: distance from the axis, arc length (extended past the ends) and angle round the axis."""

    def __init__(self, ctrl, spacing=0.003):
        self.p = _spline(ctrl, spacing)
        self.t, self.n, self.b = frames(self.p)
        seg = np.linalg.norm(np.diff(self.p, axis=0), axis=1)
        self.s = np.concatenate([[0.0], np.cumsum(seg)])
        self.tree = cKDTree(self.p)

    def s_of(self, point):
        return float(self.s[self.tree.query(np.asarray(point, float))[1]])

    def coords(self, vol, reach):
        x, y, z = vol.axes()
        X, Y, Z = np.broadcast_arrays(x, y, z)
        q = np.stack([X.ravel(), Y.ravel(), Z.ravel()], -1).astype(np.float64)
        d, i = self.tree.query(q, distance_upper_bound=reach)
        ok = np.isfinite(d)
        i = np.where(ok, i, 0)
        rel = q - self.p[i]
        ax = np.einsum("ij,ij->i", rel, self.t[i])
        perp = rel - ax[:, None] * self.t[i]
        rho = np.linalg.norm(perp, axis=1)
        theta = np.arctan2(np.einsum("ij,ij->i", perp, self.b[i]), np.einsum("ij,ij->i", perp, self.n[i]))
        s = self.s[i] + np.where((i == 0) | (i == len(self.p) - 1), ax, 0.0)
        rho = np.where(ok, rho, np.inf)
        shape = X.shape
        return rho.reshape(shape), s.reshape(shape), theta.reshape(shape), perp.reshape(shape + (3,))


# ----------------------------------------------------------------------------------------------- liver
LIVER_LO, LIVER_HI = (-1.46, -0.36, -0.7), (1.12, 1.3, 0.9)
LIVER_BODY = [ellipsoid((-0.55, 0.3, 0.1), (0.86, 0.9, 0.72)), ellipsoid((-0.05, 0.42, 0.18), (0.56, 0.62, 0.58)),
              ellipsoid((0.4, 0.6, 0.2), (0.58, 0.27, 0.45)), ellipsoid((0.78, 0.62, 0.14), (0.32, 0.1, 0.26))]
CAUDATE = [ellipsoid((-0.05, 0.43, -0.2), (0.115, 0.3, 0.14)),                       # caudate lobe
           capsule((-0.05, 0.25, -0.16), (-0.28, 0.2, -0.1), 0.065),                  # caudate process
           sphere((-0.01, 0.16, -0.14), 0.07)]                                          # papillary process


def _gb_shapes(extra=0.0):
    path = _spline(GB_CTRL, 0.02)
    r = np.interp(np.linspace(0, 1, len(path)), np.linspace(0, 1, len(GB_R)), GB_R) + extra
    shapes = _path_shapes(path, r)
    shapes.append(ellipsoid((-0.3, 0.02, 0.2), (0.065 + extra, 0.06 + extra, 0.075 + extra)))   # Hartmann's pouch
    return shapes


def _liver_field(lo, hi, vox, porta_lining=False):
    """The liver as one signed-distance field (optionally returning the hilar-plate lining of the porta too)."""
    v = Volume(lo, hi, vox)
    # right lobe, middle, left lobe and the thin tip of the left lobe
    v.add(LIVER_BODY[0])
    for shape, k in zip(LIVER_BODY[1:], (0.28, 0.22, 0.12)):
        v.add(shape, "smooth", k)
    x, y, z = v.axes()
    # visceral surface: a smooth-cornered slice gives the sharp inferior border
    dv = (_yv(x, z) - y) / 1.06
    v.d[...] = _smax(v.d, dv, 0.05)
    # posterior surface flattened against the diaphragm and the vertebral column
    zp = -0.6 + 0.26 * np.exp(-((x + 0.1) / 0.38) ** 2)
    v.d[...] = _smax(v.d, zp - z, 0.1)
    # caudate lobe, caudate process and papillary process on the posterior visceral surface
    for shape, k in zip(CAUDATE, (0.07, 0.05, 0.04)):
        v.add(shape, "smooth", k)
    # impressions: heart (above), stomach (under the left lobe), right kidney, duodenum
    v.add(sphere((0.12, 1.62, 0.2), 0.72), "smooth_subtract", 0.12)
    v.add(ellipsoid((0.5, 0.06, 0.05), (0.44, 0.36, 0.32)), "smooth_subtract", 0.08)
    v.add(ellipsoid((-0.72, -0.18, -0.38), (0.24, 0.4, 0.2)), "smooth_subtract", 0.06)
    v.add(capsule((-0.3, -0.24, 0.26), (-0.47, -0.27, 0.1), 0.16), "smooth_subtract", 0.05)
    # the aorta keeps its distance behind the caudate lobe (the crura lie between)
    v.add_all(_path_shapes(_spline(AORTA_CTRL, 0.05), AORTA_R + 0.04), "smooth_subtract", 0.03)
    # groove for the IVC, fissures for the ligamentum teres and venosum, notch in the inferior border
    v.add_all(_path_shapes(_spline(IVC_CTRL, 0.03), IVC_R + 0.008), "smooth_subtract", 0.02)
    teres = [(0.055, 0.19, 0.3), _on_visceral(0.055, 0.5, 0.0), _on_visceral(0.055, 0.66, 0.0),
             _on_visceral(0.055, 0.8, 0.0)]
    v.add_all(_path_shapes(_spline(teres, 0.02), 0.04), "smooth_subtract", 0.025)
    venosum = [(0.055, 0.2, 0.05), (0.06, 0.26, -0.1), (0.04, 0.38, -0.25), (-0.02, 0.6, -0.33),
               (-0.13, 0.8, -0.33)]
    v.add_all(_path_shapes(_spline(venosum, 0.02), 0.03), "smooth_subtract", 0.02)
    # gallbladder fossa
    v.add_all(_gb_shapes(0.01), "smooth_subtract", 0.02)
    # porta hepatis: a transverse fissure between the quadrate and caudate lobes
    a, b = _on_visceral(-0.33, 0.06, 0.035), _on_visceral(0.05, 0.08, 0.035)
    lining = None
    if porta_lining:
        cap_fn, _, _ = capsule(a, b, 0.08)
        dc = cap_fn(x, y, z)
        lining = v.copy(np.maximum(v.d, np.abs(dc - 0.074) - 0.0065))
    v.add(capsule(a, b, 0.081), "smooth_subtract", 0.015)
    return v, lining


def _liver_regions(x, y, z):
    """Signed region functions (negative inside) for the four lobes."""
    yv = _yv(x, z)
    x_gb = -0.285 - 0.3 * (z - 0.17)                        # line of the gallbladder fossa
    # right/left boundary: the falciform line in front, the fissure for the ligamentum venosum behind, which
    # swings to the right towards the IVC at the top of the caudate lobe
    xb = 0.055 - 0.19 * _smoothstep((y - 0.45) / 0.4) * _smoothstep((-z - 0.05) / 0.2)
    left = xb - x
    # the quadrate lobe is a visceral-surface lobe: it stops where the anterior surface is nearer
    quad = _max(x - 0.055, x_gb - x, 0.14 - z, y - (yv + 0.3), (y - yv) / 1.06 - (0.73 - z) * 0.9)
    # the caudate lobe is the bulge itself (with its caudate and papillary processes), so its border runs round
    # the base of the bulge
    caud = CAUDATE[0][0](x, y, z) - 0.04
    for f, grow in zip(CAUDATE[1:], (0.03, 0.03)):
        caud = np.minimum(caud, f[0](x, y, z) - grow)
    caud = _max(caud, x - xb, -0.36 - x)
    right = _max(x - xb, -quad, -caud)
    return {"right": right, "left": left, "quadrate": quad, "caudate": caud}


def _bare_bounds(x):
    s = np.clip((x + 1.16) / 1.0, 0.0, 1.0) ** 0.7
    return 0.64 - 0.33 * s, 0.64 + 0.34 * s


def build_liver(vox=0.0105):
    parts = []
    v, _ = _liver_field(LIVER_LO, LIVER_HI, vox)
    x, y, z = v.axes()
    regions = _liver_regions(x, y, z)
    names = {"right": "Right lobe of liver", "left": "Left lobe of liver", "quadrate": "Quadrate lobe",
             "caudate": "Caudate lobe"}
    for key, reg in regions.items():
        lobe = v.copy(np.maximum(v.d, reg + 0.003))
        parts.append(sdf_part(lobe, names[key], "Liver", C[key], DESC[key], category="organ", smooth=1.0,
                              rank=LIVER_RANK, bulk=True))
    _, lining = _liver_field((-0.5, -0.04, -0.14), (0.2, 0.36, 0.24), 0.0055, porta_lining=True)
    parts.append(sdf_part(lining, "Porta hepatis", "Liver", C["porta"], DESC["porta"], category="fascia",
                          smooth=0.8, rank=LIVER_RANK, bulk=True))

    # posterior surface: bare area, coronary and right triangular ligaments on a finer grid
    pv, _ = _liver_field((-1.3, 0.2, -0.72), (-0.05, 1.12, -0.05), 0.0068)
    x, y, z = pv.axes()
    D = pv.d
    y_lo, y_hi = _bare_bounds(x)
    region = _max(y_lo - y, y - y_hi, -1.16 - x, x + 0.13, z + 0.16)
    bare = pv.copy(np.maximum(np.abs(D - 0.005) - 0.0072, region))
    parts.append(sdf_part(bare, "Bare area of liver", "Liver", C["bare"], DESC["bare"], category="organ",
                          smooth=0.8, rank=LIVER_RANK, bulk=True, detail=(0.3, 70.0, 0.2, 0)))
    band = np.maximum(D - 0.05, -D - 0.004)
    xs = np.maximum(-1.15 - x, x + 0.37)          # stops at the right edge of the IVC
    fin_hi = _max(np.abs(y - y_hi - 0.004) - 0.0075, band, xs, z + 0.14)
    fin_lo = _max(np.abs(y - y_lo + 0.004) - 0.0075, band, xs, z + 0.14)
    parts.append(sdf_part(pv.copy(np.minimum(fin_hi, fin_lo)), "Coronary ligament", "Liver ligaments",
                          C["coronary"], DESC["coronary"], category="serosa", smooth=0.7, rank=LIVER_RANK, bulk=True))
    tri = _max(np.abs(y - 0.64) - 0.0075, np.maximum(D - 0.13, -D - 0.004), x + 1.1, z - 0.05)
    parts.append(sdf_part(pv.copy(tri), "Right triangular ligament", "Liver ligaments", C["coronary"],
                          DESC["rtri"], category="serosa", smooth=0.7, rank=LIVER_RANK, bulk=True))

    # falciform ligament: a sagittal sheet standing off the anterior and superior surfaces, its free edge along
    # the round ligament
    fv, _ = _liver_field((0.02, -0.62, -0.1), (0.1, 1.2, 1.02), 0.004)
    x, y, z = fv.axes()
    D = fv.d
    h = (0.07 + 0.2 * _smoothstep((0.3 - y) / 0.45) * _smoothstep((z - 0.3) / 0.3)) * _smoothstep((z + 0.02) / 0.3)
    n = np.array([0.355, 0.935])
    edge = -((y - 0.0) * n[0] + (z - 0.8) * n[1])
    sheet = _max(np.abs(x - 0.058) - 0.006, D - h, -D - 0.004, edge, -0.3 - y, z - 0.95)
    parts.append(sdf_part(fv.copy(sheet), "Falciform ligament", "Liver ligaments", C["falciform"], DESC["falciform"],
                          category="serosa", smooth=0.7, rank=LIVER_RANK, bulk=True))

    # left triangular ligament on the upper surface of the left lobe
    lv, _ = _liver_field((0.3, 0.45, -0.35), (1.18, 1.0, 0.25), 0.005)
    x, y, z = lv.axes()
    D = lv.d
    zc = -0.04 + 0.12 * (x - 0.3)
    h = 0.03 + 0.05 * _smoothstep((x - 0.5) / 0.45)
    tri = _max(np.abs(z - zc) - 0.0065, D - h, -D - 0.004, 0.36 - x, 0.5 - y, x - 1.07)
    parts.append(sdf_part(lv.copy(tri), "Left triangular ligament", "Liver ligaments", C["coronary"], DESC["ltri"],
                          category="serosa", smooth=0.7, rank=LIVER_RANK, bulk=True))

    # round ligament in its fissure and the free edge of the falciform ligament, and the ligamentum venosum
    teres = [LPV_CTRL[-1], _on_visceral(0.057, 0.45, 0.0), _on_visceral(0.058, 0.66, -0.005),
             _on_visceral(0.058, 0.79, -0.02), (0.058, -0.12, 0.85), (0.058, -0.3, 0.915)]
    parts.append(mesh_part(_tube(teres, 0.02, 18, rough=0.05, seed=3), "Round ligament of liver (ligamentum teres)",
                           "Liver ligaments", C["teres"], DESC["teres"], category="ligament", rank=LIVER_RANK,
                           bulk=True))
    venosum = [(0.055, 0.2, 0.06), (0.06, 0.26, -0.1), (0.04, 0.38, -0.25), (-0.02, 0.6, -0.33), (-0.13, 0.8, -0.33)]
    parts.append(mesh_part(_tube(venosum, 0.013, 14, rough=0.05, seed=4), "Ligamentum venosum", "Liver ligaments",
                           C["venosum"], DESC["venosum"], category="ligament", rank=LIVER_RANK,
                           bulk=True))

    # hepatic veins inside the liver, draining to the IVC just below the diaphragm
    hv = Mesh()
    hv.extend(_tube([(-0.28, 0.93, -0.3), (-0.5, 0.8, -0.18), (-0.78, 0.6, -0.02), (-1.0, 0.42, 0.12)],
                    [0.05, 0.04, 0.025, 0.008], 20, seed=11))
    hv.extend(_tube([(-0.62, 0.72, -0.1), (-0.7, 0.45, -0.28), (-0.8, 0.3, -0.34)], [0.022, 0.014, 0.006], 14))
    hv.extend(_tube([(-0.78, 0.6, -0.02), (-0.95, 0.75, 0.2)], [0.02, 0.006], 14))
    hv.extend(_tube([(-0.2, 0.95, -0.26), (-0.23, 0.78, -0.02), (-0.3, 0.55, 0.3), (-0.34, 0.35, 0.55)],
                    [0.045, 0.035, 0.022, 0.008], 20, seed=12))
    hv.extend(_tube([(-0.25, 0.7, 0.1), (-0.5, 0.6, 0.32)], [0.018, 0.006], 14))
    hv.extend(_tube([(-0.26, 0.6, 0.22), (-0.08, 0.5, 0.42)], [0.016, 0.006], 14))
    hv.extend(_tube([(-0.17, 0.96, -0.26), (0.05, 0.9, -0.14), (0.35, 0.78, 0.0), (0.72, 0.62, 0.15)],
                    [0.04, 0.03, 0.02, 0.007], 20, seed=13))
    hv.extend(_tube([(0.3, 0.8, -0.02), (0.42, 0.62, 0.3)], [0.016, 0.006], 14))
    parts.append(mesh_part(hv, "Hepatic veins", "Veins", C["ivc"], DESC["hv"], category="vein", rank=LIVER_RANK))
    return parts


# ----------------------------------------------------------------------------------------------- gallbladder
def build_gallbladder(vox=0.005):
    parts = []
    lo = np.min(np.asarray(GB_CTRL), axis=0) - 0.18
    hi = np.max(np.asarray(GB_CTRL), axis=0) + 0.18
    v = Volume(lo, hi, vox)
    v.add_all(_gb_shapes(0.0), "smooth", 0.03)
    v.displace(0.004, 9.0, 3, seed=21)
    axis = _Axis(GB_CTRL, 0.004)
    _, s, _, _ = axis.coords(v, 1.0)
    t = s / axis.s[-1]
    for name, key, t0, t1 in (("Fundus of gallbladder", "gb_fundus", -1.0, 0.2),
                              ("Body of gallbladder", "gb_body", 0.2, 0.66),
                              ("Neck of gallbladder", "gb_neck", 0.66, 2.0)):
        d = np.maximum(v.d, np.maximum(t0 - t, t - t1) * axis.s[-1] + 0.002)
        parts.append(sdf_part(v.copy(d), name, "Gallbladder & bile ducts", C[key], DESC[key], category="organ",
                              smooth=1.0))
    # cystic duct with the spiral fold of Heister showing through its wall
    path = _spline(CYSTIC_CTRL, 0.004)
    sw = Sweep(path, 28, 90)
    spiral = lambda T, S: 0.2 * np.maximum(np.cos(T - S * 2 * math.pi * 5.0), 0.0) ** 3
    parts.append(mesh_part(sw.solid(rmul(taper([0.024, 0.018, 0.018, 0.019]), rsum(1.0, spiral))), "Cystic duct",
                           "Gallbladder & bile ducts", C["cystic"], DESC["cystic"]))
    return parts


# ----------------------------------------------------------------------------------------------- bile ducts
def build_ducts():
    parts = []
    g = "Gallbladder & bile ducts"
    rhd = _tube(RHD_CTRL, [0.02, 0.021], 20, seed=31)
    rhd.extend(_pedicle_mesh(_pedicle_paths("right", RPV_CTRL[-1], 5), 0.017,
                             np.subtract(RHD_CTRL[0], RPV_CTRL[-1]), (0.0, 0.012, 0.018), 14, 32))
    parts.append(mesh_part(rhd, "Right hepatic duct", g, C["duct"], DESC["rhd"]))
    lhd = _tube(LHD_CTRL, [0.019, 0.021], 20, seed=33)
    lhd.extend(_pedicle_mesh(_pedicle_paths("left", LPV_CTRL[-1], 6), 0.015,
                             np.subtract(LHD_CTRL[0], LPV_CTRL[-1]), (0.0, 0.012, 0.018), 14, 34))
    parts.append(mesh_part(lhd, "Left hepatic duct", g, C["duct"], DESC["lhd"]))
    parts.append(mesh_part(_tube(CHD_CTRL, [0.026, 0.026, 0.027], 24, seed=35), "Common hepatic duct", g, C["duct"],
                           DESC["chd"]))
    parts.append(mesh_part(_tube(CBD_CTRL, [0.03, 0.031, 0.03, 0.028, 0.022, 0.016], 24, seed=36),
                           "Common bile duct", g, C["cbd"], DESC["cbd"]))
    # ampulla: the common channel inside the duodenal wall, and the sphincter muscle round it
    out = AMPULLA + np.array([-0.018, -0.006, 0.014])
    v = Volume(AMPULLA - 0.09, AMPULLA + 0.09, 0.0022)
    v.add(round_cone(AMPULLA + np.array([0.012, 0.01, -0.012]), out, 0.018, 0.009), "smooth", 0.01)
    parts.append(sdf_part(v, "Hepatopancreatic ampulla (of Vater)", g, C["ampulla"], DESC["ampulla"], smooth=0.8))
    s = Volume(AMPULLA - 0.1, AMPULLA + 0.1, 0.0022)
    cbd_end = _spline(CBD_CTRL, 0.004)[-22:]
    mpd_end = _spline(MPD_CTRL, 0.004)[-16:]
    s.add_all(_path_shapes(cbd_end, 0.031) + _path_shapes(mpd_end, 0.024)
              + [round_cone(AMPULLA + np.array([0.012, 0.01, -0.012]), out, 0.029, 0.018)], "smooth", 0.008)
    inner = s.copy()
    inner.d[...] = 1e3
    inner.add_all(_path_shapes(cbd_end, 0.02) + _path_shapes(mpd_end, 0.014)
                  + [round_cone(AMPULLA + np.array([0.012, 0.01, -0.012]), out, 0.019, 0.01)], "smooth", 0.008)
    s.d[...] = np.maximum(s.d, -inner.d)
    parts.append(sdf_part(s, "Sphincter of Oddi (hepatopancreatic sphincter)", g, C["oddi"], DESC["oddi"],
                          category="muscle", smooth=0.8))
    return parts


# ----------------------------------------------------------------------------------------------- pancreas
PANC_AXIS = [(-0.14, -0.3, 0.17), (0.0, -0.25, 0.215), (0.2, -0.16, 0.15), (0.45, -0.05, 0.045),
             (0.7, 0.08, -0.06), (0.95, 0.2, -0.17)]


def build_pancreas(vox=0.006):
    parts = []
    g = "Pancreas"
    v = Volume((-0.48, -0.86, -0.2), (1.1, 0.34, 0.36), vox)
    v.add(ellipsoid((-0.25, -0.5, 0.05), (0.165, 0.3, 0.14)), "smooth", 0.06)
    v.add(ellipsoid((-0.06, -0.63, 0.01), (0.14, 0.072, 0.075)), "smooth", 0.07)
    path = _spline(PANC_AXIS, 0.03)
    t, _, _ = frames(path)
    L = len(path)
    for i, p in enumerate(path):
        u = i / (L - 1)
        up = np.array([0.0, 1.0, 0.0]) - t[i] * t[i][1]
        up /= np.linalg.norm(up)
        side = np.cross(t[i], up)
        R = np.stack([t[i], up, side], 1)
        hy = np.interp(u, [0, 0.12, 0.3, 0.55, 0.8, 1.0], [0.1, 0.075, 0.1, 0.112, 0.088, 0.055])
        hz = np.interp(u, [0, 0.12, 0.3, 0.55, 0.8, 1.0], [0.075, 0.05, 0.062, 0.066, 0.055, 0.04])
        hy *= 1.0 + 0.08 * math.sin(u * 17.0 + 0.6)
        v.add(ellipsoid(p, (0.06, hy, hz), rot=R), "smooth", 0.07 if u < 0.15 else 0.04)
    # lobulated surface: a warped lattice of lobules plus a little irregularity
    near = np.abs(v.d) < 0.03
    idx = np.nonzero(near)
    pts = v.lo + np.stack(idx, -1) * v.voxel
    v.d[idx] -= (0.011 * (cell_profile(pts, 0.055, seed=41, groove=0.32, dome=0.55) - 0.5)).astype(np.float32)
    v.displace(0.008, 10.0, 3, seed=42)
    # what the pancreas wraps round or is grooved by
    gut = _spline(GUT_CTRL, 0.03)
    v.add_all(_path_shapes(gut, 0.15), "smooth_subtract", 0.02)
    for ctrl, r in ((SMV_CTRL, 0.055), (SV_CTRL, 0.045), (PV_CTRL[:3], 0.07), (CBD_CTRL[1:-1], 0.036),
                    (SMA_CTRL, 0.045)):
        v.add_all(_path_shapes(_spline(ctrl, 0.02), r), "smooth_subtract", 0.015)
    for ctrl, r in ((MPD_CTRL[:-2], 0.018), (APD_CTRL[:-1], 0.012)):
        v.add_all(_path_shapes(_spline(ctrl, 0.02), r), "subtract")
    x, y, z = v.axes()

    def plane(p0, nrm):
        nrm = np.asarray(nrm, float)
        nrm = nrm / np.linalg.norm(nrm)
        return (x - p0[0]) * nrm[0] + (y - p0[1]) * nrm[1] + (z - p0[2]) * nrm[2]
    tail_p = plane((0.66, 0.06, -0.04), (0.84, 0.4, -0.36))            # > 0 : tail
    body_p = plane((0.1, -0.2, 0.18), (0.86, 0.42, -0.3))             # > 0 : body
    neck_p = plane((-0.1, -0.27, 0.18), (1.0, 0.25, 0.1))              # > 0 : neck (above the uncinate)
    unc_in = _max(y + 0.47 + 0.25 * (x + 0.12), -0.13 - x)             # region test for the uncinate process
    regions = {
        "tail": -tail_p,
        "body": np.maximum(tail_p, -body_p),
        "neck": _max(body_p, -neck_p, -unc_in),
        "uncinate": np.maximum(unc_in, body_p),
        "head": _max(neck_p, -unc_in),
    }
    names = {"head": "Head of pancreas", "uncinate": "Uncinate process of pancreas", "neck": "Neck of pancreas",
             "body": "Body of pancreas", "tail": "Tail of pancreas"}
    for key in ("head", "uncinate", "neck", "body", "tail"):
        d = np.maximum(v.d, regions[key] + 0.003)
        parts.append(sdf_part(v.copy(d), names[key], g, C[key], DESC[key], category="gland", smooth=1.0,
                              bulk=True))
    parts.append(mesh_part(_tube(MPD_CTRL, [0.009, 0.01, 0.012, 0.014, 0.015, 0.015, 0.012], 18, spacing=0.008,
                                 seed=43), "Main pancreatic duct", g, C["mpd"], DESC["mpd"]))
    parts.append(mesh_part(_tube(APD_CTRL, [0.009, 0.009, 0.008, 0.006], 16, spacing=0.008, seed=44),
                           "Accessory pancreatic duct", g, C["apd"], DESC["apd"]))
    return parts


# ----------------------------------------------------------------------------------------------- duodenum
def build_duodenum(vox=0.006):
    parts = []
    g = "Duodenum"
    axis = _Axis(GUT_CTRL, 0.003)
    sm = {k: axis.s_of(GUT_CTRL[i]) for k, i in GUT_MARKS.items()}
    s_end = axis.s[-1]
    # outer radius along the gut: antrum -> pylorus -> duodenal cap -> duodenum -> jejunum
    ks = [0.0, sm["pylorus"] - 0.1, sm["pylorus"], sm["pylorus"] + 0.1, sm["sup_flexure"], sm["inf_flexure"],
          sm["dj"], s_end]
    ro = [0.16, 0.12, 0.1, 0.13, 0.13, 0.126, 0.118, 0.112]
    ducts = _path_shapes(_spline(CBD_CTRL, 0.01)[-12:], 0.034) + _path_shapes(_spline(MPD_CTRL, 0.01)[-10:], 0.028) \
        + _path_shapes(_spline(APD_CTRL, 0.008)[-6:], 0.014)
    s2a, s2b = sm["sup_flexure"] + 0.07, sm["inf_flexure"] - 0.07
    w = np.array([-0.45, 0.0, 0.89])
    pieces = [("Pylorus (cut end of stomach)", "pylorus", "Stomach & jejunum (cut ends)", -1.0, sm["pylorus"]),
              ("Duodenum: superior part (D1)", "d1", g, sm["pylorus"], sm["sup_flexure"]),
              ("Duodenum: descending part (D2)", "d2", g, sm["sup_flexure"], sm["inf_flexure"]),
              ("Duodenum: horizontal part (D3)", "d3", g, sm["inf_flexure"], sm["d3d4"]),
              ("Duodenum: ascending part (D4)", "d4", g, sm["d3d4"], sm["dj"]),
              ("Jejunum (cut)", "jejunum", "Stomach & jejunum (cut ends)", sm["dj"], s_end + 1.0)]
    mucosa = Mesh()
    for name, key, g_name, s0, s1 in pieces:
        sel = (axis.s >= max(s0, 0.0) - 0.05) & (axis.s <= min(s1, s_end) + 0.05)
        pts = axis.p[sel]
        lo = pts.min(axis=0) - 0.2
        hi = pts.max(axis=0) + 0.2
        v = Volume(lo, hi, vox * (0.84 if key == "d2" else 1.3))
        rho, s, th, perp = axis.coords(v, 0.2)
        r_out = np.interp(s, ks, ro)
        wall = np.where(np.abs(s - sm["pylorus"]) < 0.06, 0.022 + 0.045 * np.cos((s - sm["pylorus"]) / 0.06
                                                                                  * math.pi / 2) ** 2, 0.022)
        r_in = r_out - wall
        cut = np.maximum(s0 - s, s - s1) + 0.002
        dw = _max(rho - r_out, (r_in - rho), cut)
        # the window in the anterolateral wall of D2
        win = _max(s2a - s, s - s2b, -(perp @ w) - 0.1 * rho)
        dw = np.maximum(dw, -win)
        # circular folds from the end of the cap on
        fold_on = _smoothstep((s - (sm["pylorus"] + 0.22)) / 0.12)
        crescent = 0.55 + 0.45 * np.cos(th * 1.0 + s * 9.0)
        fold = 0.03 * fold_on * np.maximum(np.cos(2 * math.pi * s / 0.052), 0.0) ** 2 * np.clip(crescent * 1.5, 0, 1)
        if key == "d2":
            # the folds part round the papilla and its longitudinal fold
            x, y, z = v.axes()
            px, pz = PAPILLA_APEX[0], PAPILLA_APEX[2]
            yy = np.clip(y, PAPILLA_APEX[1] - 0.13, PAPILLA_APEX[1] + 0.06)
            dpap = np.sqrt((x - px) ** 2 + (y - yy) ** 2 + (z - pz) ** 2)
            dmin = np.sqrt((x - MINOR_TIP[0]) ** 2 + (y - MINOR_TIP[1]) ** 2 + (z - MINOR_TIP[2]) ** 2)
            fold = fold * _smoothstep((dpap - 0.035) / 0.04) * _smoothstep((dmin - 0.02) / 0.03)
        r_m = r_in - 0.002
        dm = _max(rho - r_m, (r_m - 0.016 - fold) - rho, cut)
        dm = np.maximum(dm, -win)
        wv = v.copy(dw.astype(np.float32))
        mv = v.copy(dm.astype(np.float32))
        # the ducts pass through the posteromedial wall of D2 to the papillae
        if key == "d2":
            wv.add_all(ducts, "subtract")
            mv.add_all(ducts, "subtract")
            # longitudinal fold below the major papilla and hooding fold above it
            apex = PAPILLA_APEX
            u = np.array([-0.707, 0.0, 0.707])            # from the posteromedial wall into the lumen
            tan = np.array([0.707, 0.0, 0.707])
            base = apex + u * 0.016
            mv.add(capsule(base + (0.0, -0.03, 0.0), base + (0.0, -0.12, 0.0), 0.013), "smooth", 0.012)
            mv.add(capsule(base + (0.0, 0.05, 0.0) - tan * 0.035, base + (0.0, 0.05, 0.0) + tan * 0.03, 0.011),
                   "smooth", 0.01)
            mv.add_all(ducts, "subtract")
        rank = 0.0
        parts.append(sdf_part(wv, name, g_name, C[key], DESC[key], category="organ", smooth=0.9, bulk=True,
                              rank=rank))
        if key not in ("pylorus", "jejunum"):
            mucosa.extend(mv.mesh(0.8))
    parts.append(mesh_part(mucosa, "Duodenal mucosa (circular folds)", g, C["mucosa"], DESC["mucosa"],
                           category="mucosa", bulk=True))
    # papillae
    pv = Volume(AMPULLA - 0.08, AMPULLA + 0.08, 0.002)
    apex = AMPULLA + np.array([-0.018, -0.006, 0.014])
    pv.add(ellipsoid(apex + np.array([-0.006, 0.0, 0.005]), (0.036, 0.048, 0.036)), "smooth", 0.014)
    pv.add(capsule(apex, AMPULLA + np.array([0.01, 0.008, -0.012]), 0.034), "smooth", 0.012)
    pv.add(sphere(apex + np.array([-0.034, -0.006, 0.03]), 0.008), "smooth_subtract", 0.004)   # orifice
    pv.add(round_cone(AMPULLA + np.array([0.012, 0.01, -0.012]), apex, 0.02, 0.0105), "subtract")
    parts.append(sdf_part(pv, "Major duodenal papilla", g, C["papilla"], DESC["major_pap"], category="mucosa",
                          smooth=0.8))
    mv = Volume(MINOR_PAP - 0.05, MINOR_PAP + 0.05, 0.002)
    mv.add(ellipsoid(MINOR_TIP, (0.019, 0.022, 0.019)), "smooth", 0.008)
    mv.add(capsule(MINOR_TIP, MINOR_PAP + np.array([0.012, 0.0, -0.003]), 0.014), "smooth", 0.006)
    mv.add(sphere(MINOR_TIP + np.array([-0.019, 0.0, 0.004]), 0.0045), "smooth_subtract", 0.002)
    parts.append(sdf_part(mv, "Minor duodenal papilla", g, C["papilla"], DESC["minor_pap"], category="mucosa",
                          smooth=0.8))
    return parts


# ----------------------------------------------------------------------------------------------- vessels
def build_vessels():
    parts = []
    gv, ga = "Veins", "Arteries"
    pv = _tube(PV_CTRL, [0.066, 0.064, 0.062, 0.062], 32, seed=51)
    pv.extend(_tube(RPV_CTRL, [0.05, 0.047, 0.045], 26, seed=52))
    pv.extend(_pedicle_mesh(_pedicle_paths("right", RPV_CTRL[-1], 5), 0.036, n_theta=18, seed=53))
    pv.extend(_tube(LPV_CTRL, [0.04, 0.038, 0.038, 0.036, 0.034], 26, seed=54))
    pv.extend(_pedicle_mesh(_pedicle_paths("left", LPV_CTRL[-1], 6), 0.028, n_theta=18, seed=55))
    pv.extend(_branches(LPV_CTRL[1], [(-0.05, 0.4, -0.2)], 0.018, 56))
    parts.append(mesh_part(pv, "Hepatic portal vein", gv, C["portal"], DESC["portal"], category="vein"))
    parts.append(mesh_part(_tube(SV_CTRL, [0.045, 0.043, 0.042, 0.044, 0.046, 0.05], 26, seed=57), "Splenic vein",
                           gv, C["portal"], DESC["splenic_v"], category="vein"))
    parts.append(mesh_part(_tube(SMV_CTRL, [0.05, 0.052, 0.054, 0.056, 0.06], 28, seed=58),
                           "Superior mesenteric vein", gv, C["portal"], DESC["smv"], category="vein"))
    parts.append(mesh_part(_tube(IMV_CTRL, [0.024, 0.025, 0.026, 0.027, 0.028], 20, seed=59),
                           "Inferior mesenteric vein", gv, C["portal"], DESC["imv"], category="vein"))
    parts.append(mesh_part(_tube(IVC_CTRL, [0.115, 0.11, 0.11, 0.115, 0.12], 40, seed=60),
                           "Inferior vena cava", gv, C["ivc"], DESC["ivc"], category="vein"))

    parts.append(mesh_part(_tube(AORTA_CTRL, [AORTA_R, AORTA_R * 0.97, AORTA_R * 0.92], 40, seed=61),
                           "Abdominal aorta", ga, C["artery"], DESC["aorta"], category="artery"))
    parts.append(mesh_part(_tube([COELIAC_O, (0.08, 0.025, -0.2), TRIFURC], 0.03, 22, seed=62), "Coeliac trunk",
                           ga, C["artery"], DESC["coeliac"], category="artery"))
    parts.append(mesh_part(_tube(CHA_CTRL, [0.025, 0.024, 0.023], 20, seed=63), "Common hepatic artery", ga,
                           C["artery"], DESC["cha"], category="artery"))
    parts.append(mesh_part(_tube(PHA_CTRL, [0.02, 0.019, 0.018], 20, seed=64), "Hepatic artery proper", ga,
                           C["artery"], DESC["pha"], category="artery"))
    rha = _tube(RHA_CTRL, [0.015, 0.014, 0.013], 16, seed=65)
    rha.extend(_pedicle_mesh(_pedicle_paths("right", RPV_CTRL[-1], 5), 0.011,
                             np.subtract(RHA_CTRL[-1], RPV_CTRL[-1]), (0.0, -0.004, 0.03), 10, 66))
    parts.append(mesh_part(rha, "Right hepatic artery", ga, C["artery"], DESC["rha"], category="artery"))
    lha = _tube(LHA_CTRL, [0.013, 0.012, 0.011], 16, seed=67)
    lha.extend(_pedicle_mesh(_pedicle_paths("left", LPV_CTRL[-1], 6), 0.009,
                             np.subtract(LHA_CTRL[-1], LPV_CTRL[-1]), (0.0, -0.004, 0.03), 10, 68))
    parts.append(mesh_part(lha, "Left hepatic artery", ga, C["artery"], DESC["lha"], category="artery"))
    ca = _tube(CYSTIC_A_CTRL, [0.009, 0.008, 0.007, 0.005], 14, seed=69)
    ca.extend(_tube([CYSTIC_A_CTRL[2], (-0.26, 0.08, 0.22), (-0.3, 0.04, 0.33)], [0.006, 0.004, 0.003], 12))
    parts.append(mesh_part(ca, "Cystic artery", ga, C["artery"], DESC["cystic_a"], category="artery"))
    gda = _tube(GDA_CTRL, [0.016, 0.015, 0.014, 0.012], 16, seed=70)
    gda.extend(_tube([GDA_CTRL[-2], (-0.05, -0.49, 0.3), (0.08, -0.48, 0.38)], [0.011, 0.01, 0.009], 14))
    parts.append(mesh_part(gda, "Gastroduodenal artery", ga, C["artery"], DESC["gda"], category="artery"))
    parts.append(mesh_part(_tube(SPLENIC_A_CTRL, [0.028, 0.026, 0.025, 0.024, 0.024], 22, seed=71),
                           "Splenic artery", ga, C["artery"], DESC["splenic_a"], category="artery"))
    parts.append(mesh_part(_tube(LGA_CTRL, [0.016, 0.015, 0.014], 16, seed=72), "Left gastric artery (cut)", ga,
                           C["artery"], DESC["lga"], category="artery"))
    parts.append(mesh_part(_tube(SMA_CTRL, [0.036, 0.035, 0.034, 0.033, 0.032], 24, seed=73),
                           "Superior mesenteric artery", ga, C["artery"], DESC["sma"], category="artery"))
    return parts


GROUP_ORDER = ["Liver", "Liver ligaments", "Gallbladder & bile ducts", "Pancreas", "Duodenum",
               "Stomach & jejunum (cut ends)", "Veins", "Arteries"]


def build_hepatobiliary():
    parts = build_liver() + build_gallbladder() + build_ducts() + build_pancreas() + build_duodenum() \
        + build_vessels()
    return sorted(parts, key=lambda p: GROUP_ORDER.index(p.group))       # stable: keeps the order within groups
