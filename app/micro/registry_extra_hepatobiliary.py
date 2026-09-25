"""Gross hepatobiliary specimen: liver, gallbladder, bile ducts, pancreas and duodenum."""
import math

from .base import MicroModel
from .hepatobiliary import build_hepatobiliary


def register_all(register):
    model = MicroModel(
        "hepatobiliary", "Liver, gallbladder, bile ducts & pancreas",
        "The upper abdominal digestive glands in place, seen from the front: the liver with its four lobes, its "
        "ligaments and bare area; the gallbladder and the extrahepatic bile ducts from the porta hepatis to the "
        "hepatopancreatic ampulla; the pancreas curled in the C of the duodenum, whose second part is opened to "
        "show the major and minor papillae; and the portal vein, hepatic arteries, IVC and hepatic veins. "
        "'Separate layers' lifts the liver off the porta hepatis; 'Tissue opacity' makes the liver, pancreas and "
        "duodenum see-through, showing the hepatic veins, the intrahepatic branches and the pancreatic ducts.",
        build_hepatobiliary,
        targets={"structures": ["Liver", "Gallbladder", "Pancreas", "Duodenum", "Bile duct", "Pancreatic duct",
                                "Accessory pancreatic duct", "Porta hepatis", "Right lobe of liver",
                                "Left lobe of liver", "Quadrate lobe", "Caudate process", "Bare area of liver",
                                "Fissure for ligamentum teres", "Fossa for gallbladder", "Visceral surface of liver",
                                "Fundus of gallbladder", "Body of gallbladder", "Neck of gallbladder",
                                "Head of pancreas", "Neck of pancreas", "Body of pancreas", "Tail of pancreas",
                                "Uncinate process of pancreas", "Hepatic portal vein", "Proper hepatic artery",
                                "Common hepatic artery", "Hepatic veins"]},
        histology=["liver", "gallbladder", "pancreas", "duodenum"],
        related=["liver_lobule", "pancreas", "duodenum"],
        clinical=[
            ("Gallstones (cholelithiasis)",
             "Mostly cholesterol stones, formed when bile is supersaturated with cholesterol relative to bile salts "
             "and lecithin and the gallbladder empties poorly (risk: female, obesity, pregnancy, rapid weight loss, "
             "age); pigment stones come with haemolysis or infection. Most are silent. A stone impacted in the neck "
             "(Hartmann's pouch) or cystic duct causes biliary colic - constant right upper quadrant or epigastric "
             "pain after fatty meals, referred to the right shoulder tip or below the scapula. Ultrasound is the "
             "first test; symptomatic stones are treated by laparoscopic cholecystectomy after the critical view of "
             "safety in Calot's triangle."),
            ("Acute cholecystitis",
             "Persistent obstruction of the cystic duct leads to chemical then bacterial inflammation of a distended "
             "gallbladder: constant RUQ pain, fever, raised white count and a positive Murphy's sign (inspiration "
             "arrested by pain on palpating the fundus at the tip of the ninth costal cartilage). Ultrasound shows "
             "a thick wall, pericholecystic fluid and a stone in the neck. Because the cystic artery is an end "
             "artery, distension can cause gangrene and perforation. Stones eroding into the duodenum can cause "
             "gallstone ileus."),
            ("Obstructive jaundice",
             "A stone in the common bile duct (choledocholithiasis), a carcinoma of the pancreatic head, ampulla or "
             "bile duct (hilar Klatskin tumour), or a stricture blocks bile: conjugated hyperbilirubinaemia with "
             "dark urine, pale stools, itching and raised ALP/GGT. Courvoisier's law: a palpable, painless "
             "gallbladder with jaundice is unlikely to be due to stones (a stone-scarred gallbladder cannot "
             "distend) - think pancreatic cancer. Obstruction plus infection gives ascending cholangitis (Charcot's "
             "triad: fever, jaundice, RUQ pain), treated by urgent biliary drainage at ERCP."),
            ("Gallstone pancreatitis",
             "The bile duct and main pancreatic duct share the hepatopancreatic ampulla. A small stone passing down "
             "the bile duct and lodging at the ampulla blocks pancreatic outflow and lets bile reflux into the "
             "pancreatic duct; trypsin is activated inside the gland and autodigestion follows. Gallstones and "
             "alcohol cause most acute pancreatitis: severe epigastric pain boring through to the back, vomiting, "
             "serum lipase over three times normal. Complications include necrosis, pseudocyst in the lesser sac, "
             "splenic vein thrombosis and ARDS. The gallbladder is removed in the same admission to prevent "
             "recurrence."),
            ("Portal hypertension",
             "Raised pressure in the portal vein (portal-hepatic venous gradient over 10 mmHg), usually from "
             "cirrhosis; also portal or splenic vein thrombosis (pre-hepatic) and Budd-Chiari syndrome or right "
             "heart failure (post-hepatic). Portal blood diverts through portosystemic anastomoses: oesophageal "
             "and gastric varices (left gastric vein - the main cause of death by haemorrhage), rectal varices, "
             "caput medusae (paraumbilical veins along the ligamentum teres) and retroperitoneal veins, including "
             "those of the bare area. Splenomegaly with hypersplenism and ascites follow. Treatment: beta-blockers, "
             "variceal banding, and a TIPS shunt from a hepatic vein to a portal branch through the liver."),
            ("Calot's triangle & biliary variants",
             "The cystohepatic triangle (cystic duct, common hepatic duct, inferior surface of the liver) contains "
             "the cystic artery, usually from the right hepatic artery, and the cystic node. Variants are common: "
             "a low or spiral cystic duct insertion, accessory (aberrant) right hepatic ducts draining into the "
             "cystic duct, a replaced right hepatic artery from the SMA behind the portal vein, a cystic artery "
             "running in front of the common hepatic duct. Misreading them causes bile duct and arterial injury."),
        ],
        scale_note="Life size: 1 unit ≈ 10 cm (the liver is ≈ 22 cm wide). The duodenum is opened from the front; "
                   "calibres of the smaller ducts and arteries are slightly exaggerated.")
    model.metres_per_unit = 0.1
    model.cut_on = False                  # a whole specimen, not a block: open it uncut
    model.home_view = (math.radians(-12.0), math.radians(-6.0))
    model.cutaway = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    model.cut_at = (-0.3, 0.1)
    register(model)
