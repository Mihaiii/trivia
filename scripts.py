from fastcore.utils import *
from fasthtml.xtend import Script

def ThemeSwitch(sel='#theme-toggle', buttonClass = 'secondary'):
    src = """
import { proc_htmx} from "https://cdn.jsdelivr.net/gh/answerdotai/fasthtml-js/fasthtml.js";

const button = document.createElement('button');
button.id = 'theme-switch';

const moonSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
moonSvg.id = 'moon';
moonSvg.setAttribute('width', '24');
moonSvg.setAttribute('height', '18');
moonSvg.setAttribute('viewBox', '0 0 24 24');
moonSvg.setAttribute('fill', 'none');
moonSvg.setAttribute('stroke', 'currentColor');
moonSvg.setAttribute('stroke-width', '2');
moonSvg.setAttribute('stroke-linecap', 'round');
moonSvg.setAttribute('stroke-linejoin', 'round');
moonSvg.setAttribute('style', 'color: black');
const moonPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
moonPath.setAttribute('d', 'M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z');
moonSvg.appendChild(moonPath);

const sunSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
sunSvg.id = 'sun';
sunSvg.setAttribute('width', '24');
sunSvg.setAttribute('height', '18');
sunSvg.setAttribute('viewBox', '0 0 24 24');
sunSvg.setAttribute('fill', 'none');
sunSvg.setAttribute('stroke', 'currentColor');
sunSvg.setAttribute('stroke-width', '2');
sunSvg.setAttribute('stroke-linecap', 'round');
sunSvg.setAttribute('stroke-linejoin', 'round');
const sunCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
sunCircle.setAttribute('cx', '12');
sunCircle.setAttribute('cy', '12');
sunCircle.setAttribute('r', '5');
sunCircle.setAttribute('style', 'color: white');
sunSvg.appendChild(sunCircle);
const sunLines = [
  { x1: '12', y1: '1', x2: '12', y2: '3' },
  { x1: '12', y1: '21', x2: '12', y2: '23' },
  { x1: '4.22', y1: '4.22', x2: '5.64', y2: '5.64' },
  { x1: '18.36', y1: '18.36', x2: '19.78', y2: '19.78' },
  { x1: '1', y1: '12', x2: '3', y2: '12' },
  { x1: '21', y1: '12', x2: '23', y2: '12' },
  { x1: '4.22', y1: '19.78', x2: '5.64', y2: '18.36' },
  { x1: '18.36', y1: '5.64', x2: '19.78', y2: '4.22' }
];
sunLines.forEach(attrs => {
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  for (const [key, value] of Object.entries(attrs)) {
    line.setAttribute(key, value);
  }
  sunSvg.appendChild(line);
});

button.setAttribute("class", "%s")
button.setAttribute("style", "background: transparent")
button.appendChild(moonSvg);
button.appendChild(sunSvg);


function getColorSchemePreference() {
    let ls = localStorage.getItem("triviaTheme")
    if (ls) {
        return ls;
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        return 'light';
    } else {
        return 'light';
    }
}

function setIconToShow() {
    let t = me("html").attribute("data-theme");
    sunSvg.setAttribute("display", t == "light" ? "none" : "inline");
    moonSvg.setAttribute("display", t == "light" ? "inline" : "none");
}

me("html").attribute("data-theme", getColorSchemePreference())
setIconToShow()                

let selector = '%s'            
proc_htmx(selector, e => e.appendChild(button));

me(selector).on("click", _ => 
{
    let newTheme = me("html").attribute("data-theme") === "dark" ? "light" : "dark"
    me("html").attribute("data-theme", newTheme)
    localStorage.setItem("triviaTheme", newTheme)
    setIconToShow()
})

""" % (buttonClass, sel)
    return Script(src, type='module')

def enterToBid():
    src = """
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                document.getElementById('bid_btn').click();
            }
        });
        """
    return Script(src)
