#!/usr/bin/env python3
"""
Generates the LMS app v3 — Boot.dev-inspired redesign with:
- Split-pane layout (lesson left, lab right)
- Top navigation bar with chapter/lesson dropdowns
- XP & gamification system (points, streaks, achievements)
- Polished dark theme with warm gold accents
- Better code blocks with copy buttons
- Progress rings per module
- Responsive design
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from quiz_data import QUIZZES

with open(os.path.join(SCRIPT_DIR, "course_data.json"), "r") as f:
    course_data = json.load(f)

# Escape </script> tags in JSON to prevent breaking the HTML <script> block
quiz_json = json.dumps(QUIZZES).replace('</script>', '<\\/script>')
course_json = json.dumps(course_data).replace('</script>', '<\\/script>')

total_qs = sum(len(qs) for qs in QUIZZES.values())
print(f"Total quiz questions: {total_qs} across {len(QUIZZES)} lessons")

html = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backend Mastery — Go &middot; Microservices &middot; System Design</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/go.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/sql.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/protobuf.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/yaml.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/bash.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/makefile.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/typescript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.0/marked.min.js"></script>
<style>
/* ===== RESET & ROOT — Tethra Theme ===== */
:root {
  --bg-base: #0f0f0f;
  --bg-surface: #191919;
  --bg-raised: #232323;
  --bg-overlay: #2a2a2a;
  --bg-hover: #303030;
  --border-subtle: #363636;
  --border-default: #3d3d3d;
  --border-strong: #4a4a4a;
  --text-primary: #fafafa;
  --text-secondary: #a1a1a1;
  --text-muted: #6b6b6b;
  --text-faint: #4a4a4a;
  --coral: #DE7356;
  --coral-dim: #c4603f;
  --coral-glow: #DE735630;
  --coral-subtle: #DE735618;
  --coral-hover: #E8917A;
  --green: #10b981;
  --green-dim: #0d9668;
  --green-subtle: #10b98118;
  --blue: #3b82f6;
  --blue-subtle: #3b82f618;
  --purple: #a855f7;
  --purple-subtle: #a855f718;
  --red: #ef4444;
  --red-subtle: #ef444418;
  --amber: #f59e0b;
  --amber-subtle: #f59e0b18;
  --cyan: #22d3ee;
  --font-sans: 'Fira Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
  --font-mono: 'Fira Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,.4);
  --shadow-md: 0 4px 12px rgba(0,0,0,.5);
  --shadow-lg: 0 12px 40px rgba(0,0,0,.6);
  --sidebar-w: 280px;
  --topbar-h: 52px;
}
@import url('https://fonts.googleapis.com/css2?family=Fira+Mono:wght@400;500;700&family=Fira+Code:wght@400;500;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;overflow:hidden;}
body{font-family:var(--font-sans);background:var(--bg-base);color:var(--text-primary);line-height:1.6;-webkit-font-smoothing:antialiased;}
::-webkit-scrollbar{width:6px;height:6px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--border-default);border-radius:3px;}
::-webkit-scrollbar-thumb:hover{background:var(--border-strong);}

/* ===== TOP BAR ===== */
.topbar{
  position:fixed;top:0;left:0;right:0;height:var(--topbar-h);
  background:var(--bg-surface);border-bottom:1px solid var(--border-subtle);
  display:flex;align-items:center;padding:0 16px;z-index:200;gap:8px;
}
.topbar-brand{display:flex;align-items:center;gap:10px;padding-right:16px;border-right:1px solid var(--border-subtle);margin-right:8px;cursor:pointer;flex-shrink:0;}
.topbar-brand .logo{width:32px;height:32px;background:linear-gradient(135deg,var(--coral),var(--coral-hover));border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:800;color:#000;}
.topbar-brand .name{font-size:14px;font-weight:700;color:var(--text-primary);letter-spacing:-.3px;}

.topbar-nav{display:flex;align-items:center;gap:4px;flex:1;min-width:0;}
.topbar-dropdown{
  position:relative;display:flex;align-items:center;gap:6px;
  padding:6px 12px;border-radius:var(--radius-sm);cursor:pointer;
  font-size:13px;font-weight:500;color:var(--text-secondary);
  border:1px solid transparent;transition:all .15s;max-width:220px;
}
.topbar-dropdown:hover{background:var(--bg-hover);color:var(--text-primary);border-color:var(--border-subtle);}
.topbar-dropdown.active{background:var(--bg-overlay);color:var(--text-primary);border-color:var(--border-default);}
.topbar-dropdown .dd-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.topbar-dropdown .dd-arrow{font-size:8px;color:var(--text-muted);flex-shrink:0;transition:transform .2s;}
.topbar-dropdown.active .dd-arrow{transform:rotate(180deg);}
.dd-sep{color:var(--text-faint);font-size:14px;margin:0 2px;}
.dd-menu{
  position:absolute;top:calc(100% + 4px);left:0;min-width:260px;
  background:var(--bg-raised);border:1px solid var(--border-default);border-radius:var(--radius-md);
  box-shadow:var(--shadow-lg);padding:6px;z-index:300;display:none;
  max-height:400px;overflow-y:auto;
}
.dd-menu.show{display:block;}
.dd-item{
  display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:var(--radius-sm);
  cursor:pointer;font-size:13px;color:var(--text-secondary);transition:all .1s;
}
.dd-item:hover{background:var(--bg-hover);color:var(--text-primary);}
.dd-item.active{background:var(--coral-subtle);color:var(--coral);}
.dd-item .dd-check{width:16px;height:16px;border-radius:50%;border:1.5px solid var(--border-default);display:flex;align-items:center;justify-content:center;font-size:9px;flex-shrink:0;}
.dd-item.completed .dd-check{background:var(--green);border-color:var(--green);color:#fff;}
.dd-item .dd-label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dd-item .dd-meta{font-size:11px;color:var(--text-muted);flex-shrink:0;}

.topbar-right{display:flex;align-items:center;gap:12px;margin-left:auto;flex-shrink:0;}
.topbar-stat{display:flex;align-items:center;gap:5px;font-size:13px;font-weight:600;padding:4px 10px;border-radius:20px;}
.topbar-stat.xp{color:var(--coral);background:var(--coral-subtle);}
.topbar-stat.streak{color:var(--amber);background:var(--amber-subtle);}
.topbar-stat.progress{color:var(--green);background:var(--green-subtle);}
.topbar-stat .stat-icon{font-size:14px;}
.search-trigger{
  display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:var(--radius-sm);
  border:1px solid var(--border-subtle);background:var(--bg-raised);color:var(--text-muted);
  font-size:13px;cursor:pointer;transition:all .15s;
}
.search-trigger:hover{border-color:var(--border-default);color:var(--text-secondary);}
.search-trigger kbd{font-size:10px;background:var(--bg-overlay);padding:2px 6px;border-radius:3px;font-family:var(--font-sans);}
.topbar-avatar{
  width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,var(--purple),var(--blue));
  display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;cursor:pointer;
  border:2px solid var(--border-subtle);
}

/* ===== SIDEBAR ===== */
.sidebar{
  position:fixed;top:var(--topbar-h);left:0;bottom:0;width:var(--sidebar-w);
  background:var(--bg-surface);border-right:1px solid var(--border-subtle);
  display:flex;flex-direction:column;z-index:100;transition:transform .25s cubic-bezier(.4,0,.2,1);
}
.sidebar.collapsed{transform:translateX(calc(-1 * var(--sidebar-w)));}
.sidebar-scroll{flex:1;overflow-y:auto;padding:12px 0;}
.module-group{margin-bottom:2px;}
.module-header{
  display:flex;align-items:center;gap:10px;padding:10px 16px;cursor:pointer;
  font-size:12px;font-weight:700;color:var(--text-muted);text-transform:uppercase;
  letter-spacing:.6px;transition:all .15s;user-select:none;
}
.module-header:hover{color:var(--text-secondary);background:var(--bg-hover);}
.module-header .m-progress{margin-left:auto;font-size:11px;font-weight:500;color:var(--text-faint);letter-spacing:0;text-transform:none;}
.module-header .m-chevron{font-size:8px;transition:transform .2s;color:var(--text-faint);}
.module-header.expanded .m-chevron{transform:rotate(90deg);}
.module-lessons{display:none;padding:0 0 6px;}
.module-lessons.show{display:block;}
.lesson-item{
  display:flex;align-items:center;gap:8px;padding:7px 16px 7px 28px;cursor:pointer;
  font-size:13px;color:var(--text-secondary);transition:all .12s;position:relative;
}
.lesson-item:hover{background:var(--bg-hover);color:var(--text-primary);}
.lesson-item.active{background:var(--coral-subtle);color:var(--coral);}
.lesson-item.active::before{content:'';position:absolute;left:0;top:4px;bottom:4px;width:3px;background:var(--coral);border-radius:0 2px 2px 0;}
.lesson-item .l-num{width:20px;height:20px;border-radius:50%;border:1.5px solid var(--border-default);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:600;flex-shrink:0;color:var(--text-muted);}
.lesson-item .l-num.done{background:var(--green);border-color:var(--green);color:#fff;}
.lesson-item .l-title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lesson-item .l-time{font-size:11px;color:var(--text-faint);flex-shrink:0;}

/* ===== MAIN CONTENT AREA ===== */
.app-body{
  position:fixed;top:var(--topbar-h);left:var(--sidebar-w);right:0;bottom:0;
  display:flex;transition:left .25s cubic-bezier(.4,0,.2,1);
}
.app-body.sidebar-collapsed{left:0;}

/* Dashboard view */
.dash-wrap{flex:1;overflow-y:auto;padding:0;}
.dashboard{max-width:900px;margin:0 auto;padding:48px 32px;}
.dash-greeting{margin-bottom:32px;}
.dash-greeting h1{font-size:28px;font-weight:800;letter-spacing:-.5px;margin-bottom:4px;}
.dash-greeting h1 .wave{display:inline-block;animation:wave 2s ease-in-out infinite;}
@keyframes wave{0%,100%{transform:rotate(0)}25%{transform:rotate(20deg)}75%{transform:rotate(-10deg)}}
.dash-greeting p{font-size:15px;color:var(--text-secondary);}

.dash-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:36px;}
.dash-stat-card{background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:20px;transition:border-color .2s;}
.dash-stat-card:hover{border-color:var(--border-default);}
.dash-stat-card .s-label{font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;}
.dash-stat-card .s-value{font-size:26px;font-weight:800;letter-spacing:-.5px;}
.dash-stat-card .s-value.gold{color:var(--coral);}
.dash-stat-card .s-value.green{color:var(--green);}
.dash-stat-card .s-value.blue{color:var(--blue);}
.dash-stat-card .s-value.purple{color:var(--purple);}
.dash-stat-card .s-sub{font-size:12px;color:var(--text-muted);margin-top:4px;}

.dash-modules{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;}
.dash-mod-card{
  background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);
  padding:24px;cursor:pointer;transition:all .2s;position:relative;overflow:hidden;
}
.dash-mod-card:hover{border-color:var(--coral-dim);transform:translateY(-2px);box-shadow:var(--shadow-md);}
.dash-mod-card .mc-icon{
  width:44px;height:44px;border-radius:var(--radius-md);display:flex;align-items:center;
  justify-content:center;font-size:22px;margin-bottom:14px;
}
.dash-mod-card .mc-icon.mod0{background:var(--blue-subtle);color:var(--blue);}
.dash-mod-card .mc-icon.mod1{background:var(--purple-subtle);color:var(--purple);}
.dash-mod-card .mc-icon.mod2{background:var(--amber-subtle);color:var(--amber);}
.dash-mod-card .mc-icon.mod3{background:var(--green-subtle);color:var(--green);}
.dash-mod-card h3{font-size:16px;font-weight:700;margin-bottom:6px;}
.dash-mod-card p{font-size:13px;color:var(--text-secondary);margin-bottom:16px;line-height:1.5;}
.dash-mod-card .mc-footer{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--text-muted);}
.dash-mod-card .mc-bar{height:3px;background:var(--bg-overlay);border-radius:2px;margin-top:14px;overflow:hidden;}
.dash-mod-card .mc-bar-fill{height:100%;background:linear-gradient(90deg,var(--coral-dim),var(--coral-hover));border-radius:2px;transition:width .4s;}

/* ===== SPLIT PANE (lesson + lab) ===== */
.split-view{display:flex;flex:1;height:100%;}
.pane-lesson{
  flex:1;overflow-y:auto;border-right:1px solid var(--border-subtle);
  background:var(--bg-base);min-width:0;
}
.pane-lab{
  width:44%;min-width:360px;max-width:560px;overflow-y:auto;
  background:var(--bg-surface);display:flex;flex-direction:column;
}
.pane-lab.hidden{display:none;}
.pane-lesson.full{border-right:none;}

/* Lesson content */
.lesson-wrap{max-width:780px;margin:0 auto;padding:36px 32px 80px;}
.lesson-head{margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border-subtle);}
.lesson-head h1{font-size:26px;font-weight:800;letter-spacing:-.3px;margin-bottom:10px;line-height:1.2;}
.lesson-badges{display:flex;gap:8px;flex-wrap:wrap;}
.lbadge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:500;}
.lbadge.time{background:var(--blue-subtle);color:var(--blue);}
.lbadge.exercise{background:var(--green-subtle);color:var(--green);}
.lbadge.interview{background:var(--purple-subtle);color:var(--purple);}
.lbadge.lab{background:var(--coral-subtle);color:var(--coral);}

.lesson-body h2{font-size:20px;font-weight:700;margin:36px 0 14px;padding-top:14px;border-top:1px solid var(--border-subtle);color:var(--text-primary);}
.lesson-body h2:first-child{border-top:none;margin-top:0;padding-top:0;}
.lesson-body h3{font-size:16px;font-weight:700;margin:24px 0 10px;color:var(--text-primary);}
.lesson-body p{margin:0 0 14px;line-height:1.75;color:var(--text-secondary);font-size:14.5px;}
.lesson-body strong{color:var(--text-primary);font-weight:600;}
.lesson-body a{color:var(--blue);text-decoration:none;}
.lesson-body a:hover{text-decoration:underline;}
.lesson-body ul,.lesson-body ol{margin:0 0 14px 20px;color:var(--text-secondary);}
.lesson-body li{margin-bottom:5px;line-height:1.65;font-size:14.5px;}
.lesson-body hr{border:none;border-top:1px solid var(--border-subtle);margin:28px 0;}
.lesson-body code{
  font-family:var(--font-mono);font-size:.85em;background:var(--bg-raised);
  padding:2px 7px;border-radius:4px;color:var(--coral);
}
.lesson-body pre{margin:0 0 18px;border-radius:var(--radius-md);overflow:hidden;border:1px solid var(--border-subtle);position:relative;}
.lesson-body pre code{display:block;padding:16px 20px;background:var(--bg-raised);color:var(--text-primary);font-size:13px;line-height:1.6;overflow-x:auto;}
/* Code cell toolbar (Jupyter-style) */
.code-cell{position:relative;margin:0 0 18px;}
.code-cell pre{margin:0;border-radius:var(--radius-md) var(--radius-md) 0 0;border-bottom:none;}
.code-cell.no-output pre{border-radius:var(--radius-md);border-bottom:1px solid var(--border-subtle);}
.code-cell-toolbar{
  display:flex;align-items:center;gap:6px;padding:6px 10px;
  background:var(--bg-raised);border:1px solid var(--border-subtle);border-top:none;
  border-radius:0 0 var(--radius-md) var(--radius-md);
}
.code-cell-toolbar .cc-btn{
  padding:3px 10px;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;
  font-family:var(--font-sans);transition:all .12s;display:flex;align-items:center;gap:4px;
  border:1px solid var(--border-subtle);background:var(--bg-overlay);color:var(--text-secondary);
}
.code-cell-toolbar .cc-btn:hover{background:var(--bg-hover);color:var(--text-primary);border-color:var(--border-default);}
.code-cell-toolbar .cc-run{background:var(--green-subtle);color:var(--green);border-color:var(--green-dim);}
.code-cell-toolbar .cc-run:hover{background:var(--green);color:#fff;}
.code-cell-toolbar .cc-run:disabled{opacity:.5;cursor:not-allowed;}
.code-cell-toolbar .cc-run .spinner{display:inline-block;width:10px;height:10px;border:1.5px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;}
.code-cell-toolbar .cc-lang{margin-left:auto;font-size:10px;color:var(--text-faint);text-transform:uppercase;letter-spacing:.5px;}
.code-cell-output{
  border:1px solid var(--border-subtle);border-top:1px dashed var(--border-default);
  border-radius:0 0 var(--radius-md) var(--radius-md);background:var(--bg-base);
  padding:12px 16px;font-family:var(--font-mono);font-size:12px;line-height:1.5;
  white-space:pre-wrap;max-height:200px;overflow-y:auto;display:none;
}
.code-cell-output.show{display:block;}
.code-cell-output.success{color:var(--green);}
.code-cell-output.error{color:var(--red);}
.code-cell-output.running{color:var(--text-muted);font-style:italic;}
.code-cell.has-output pre{border-radius:var(--radius-md) var(--radius-md) 0 0;}
.code-cell.has-output .code-cell-toolbar{border-radius:0;}
.code-cell.has-output .code-cell-output{display:block;}

.lesson-body pre .copy-btn{
  position:absolute;top:8px;right:8px;padding:4px 10px;border-radius:var(--radius-sm);
  background:var(--bg-overlay);border:1px solid var(--border-subtle);color:var(--text-muted);
  font-size:11px;font-family:var(--font-sans);cursor:pointer;opacity:0;transition:opacity .15s;z-index:2;
}
.lesson-body pre:hover .copy-btn{opacity:1;}
.lesson-body pre .copy-btn:hover{color:var(--text-primary);border-color:var(--border-default);}
.lesson-body blockquote{border-left:3px solid var(--coral);padding:12px 20px;margin:0 0 14px;background:var(--coral-subtle);border-radius:0 var(--radius-sm) var(--radius-sm) 0;color:var(--text-secondary);font-size:14px;}
.lesson-body table{width:100%;border-collapse:collapse;margin:0 0 18px;font-size:13.5px;}
.lesson-body th{background:var(--bg-raised);border:1px solid var(--border-subtle);padding:10px 14px;text-align:left;font-weight:600;font-size:12.5px;color:var(--text-primary);}
.lesson-body td{border:1px solid var(--border-subtle);padding:10px 14px;color:var(--text-secondary);}
.lesson-body tr:hover td{background:var(--bg-surface);}

.interview-corner{background:var(--purple-subtle);border:1px solid #a78bfa33;border-radius:var(--radius-md);padding:22px;margin:22px 0;}
.interview-corner h2{color:var(--purple)!important;border-top:none!important;margin-top:0!important;padding-top:0!important;font-size:17px!important;}
.exercise-section{background:var(--green-subtle);border:1px solid #34d39933;border-radius:var(--radius-md);padding:22px;margin:22px 0;}
.exercise-section h2{color:var(--green)!important;border-top:none!important;margin-top:0!important;padding-top:0!important;font-size:17px!important;}

.lesson-complete-bar{
  margin-top:36px;padding:20px;background:var(--bg-surface);border:1px solid var(--border-subtle);
  border-radius:var(--radius-md);display:flex;align-items:center;justify-content:space-between;
}
.lesson-complete-bar span{font-size:14px;color:var(--text-secondary);}
.lesson-nav-footer{display:flex;justify-content:space-between;margin-top:20px;}
.nav-btn{
  padding:8px 16px;border-radius:var(--radius-sm);font-size:13px;font-weight:600;
  cursor:pointer;transition:all .15s;border:1px solid var(--border-default);
  background:var(--bg-surface);color:var(--text-primary);font-family:var(--font-sans);
}
.nav-btn:hover{background:var(--bg-hover);border-color:var(--border-strong);}
.nav-btn:disabled{opacity:.3;cursor:not-allowed;}
.nav-btn.primary{background:var(--coral);border-color:var(--coral);color:#000;}
.nav-btn.primary:hover{background:var(--coral-dim);}

/* ===== LAB PANE (collapsible) ===== */
.pane-lab{transition:width .3s cubic-bezier(.4,0,.2,1),min-width .3s,opacity .2s;position:relative;}
.pane-lab.collapsed{width:0!important;min-width:0!important;overflow:hidden;opacity:0;border:none;padding:0;}
.lab-toggle{
  position:absolute;top:50%;transform:translateY(-50%);z-index:10;
  width:24px;height:48px;display:flex;align-items:center;justify-content:center;
  background:var(--bg-raised);border:1px solid var(--border-default);cursor:pointer;
  color:var(--text-muted);font-size:12px;transition:all .15s;
}
.lab-toggle:hover{color:var(--text-primary);background:var(--bg-hover);}
.lab-toggle.on-lesson{right:-24px;border-radius:0 var(--radius-sm) var(--radius-sm) 0;border-left:none;}
.lab-toggle.on-lab{left:0;border-radius:var(--radius-sm) 0 0 var(--radius-sm);border-right:none;}
.lab-header{
  padding:14px 20px;border-bottom:1px solid var(--border-subtle);display:flex;
  align-items:center;gap:10px;flex-shrink:0;background:var(--bg-raised);
}
.lab-header h3{font-size:14px;font-weight:700;color:var(--coral);}
.lab-header .lab-count{font-size:12px;color:var(--text-muted);margin-left:auto;}
.lab-header .lab-close{
  background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;
  padding:2px 6px;border-radius:var(--radius-sm);transition:all .12s;margin-left:8px;
}
.lab-header .lab-close:hover{color:var(--text-primary);background:var(--bg-hover);}
.lab-tabs{display:flex;border-bottom:1px solid var(--border-subtle);flex-shrink:0;background:var(--bg-surface);}
.lab-tab{
  flex:1;padding:10px 16px;text-align:center;cursor:pointer;font-size:12px;font-weight:600;
  color:var(--text-muted);border-bottom:2px solid transparent;transition:all .12s;
}
.lab-tab:hover{color:var(--text-secondary);}
.lab-tab.active{color:var(--coral);border-bottom-color:var(--coral);}
.lab-body{flex:1;overflow-y:auto;padding:20px;}
.lab-panel{display:none;flex-direction:column;flex:1;overflow:hidden;}
.lab-panel.active{display:flex;}

/* ===== GO PLAYGROUND ===== */
.playground-wrap{display:flex;flex-direction:column;flex:1;overflow:hidden;}
.pg-editor-wrap{flex:1;display:flex;flex-direction:column;overflow:hidden;padding:12px;}
.pg-editor{
  flex:1;width:100%;resize:none;background:var(--bg-base);color:var(--text-primary);
  border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:14px;
  font-family:var(--font-mono);font-size:13px;line-height:1.6;outline:none;
  tab-size:4;-moz-tab-size:4;
}
.pg-editor:focus{border-color:var(--coral);}
.pg-toolbar{
  display:flex;align-items:center;gap:8px;padding:8px 12px;
  border-top:1px solid var(--border-subtle);background:var(--bg-raised);flex-shrink:0;
}
.pg-run-btn{
  padding:6px 16px;background:var(--green);border:none;border-radius:var(--radius-sm);
  color:#fff;font-size:12px;font-weight:700;cursor:pointer;font-family:var(--font-sans);
  display:flex;align-items:center;gap:6px;transition:all .12s;
}
.pg-run-btn:hover{background:var(--green-dim);}
.pg-run-btn:disabled{opacity:.5;cursor:not-allowed;}
.pg-run-btn .spinner{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.pg-fmt-btn{
  padding:6px 12px;background:var(--bg-overlay);border:1px solid var(--border-subtle);
  border-radius:var(--radius-sm);color:var(--text-secondary);font-size:12px;font-weight:600;
  cursor:pointer;font-family:var(--font-sans);transition:all .12s;
}
.pg-fmt-btn:hover{background:var(--bg-hover);color:var(--text-primary);}
.pg-status{margin-left:auto;font-size:11px;color:var(--text-muted);}
.pg-output-wrap{
  max-height:180px;overflow-y:auto;border-top:1px solid var(--border-subtle);
  background:var(--bg-base);flex-shrink:0;
}
.pg-output{
  padding:12px;font-family:var(--font-mono);font-size:12px;line-height:1.5;
  white-space:pre-wrap;color:var(--text-secondary);min-height:40px;
}
.pg-output.error{color:var(--red);}
.pg-output.success{color:var(--green);}
.pg-output .pg-placeholder{color:var(--text-faint);font-style:italic;}

.quiz-progress-wrap{margin-bottom:20px;}
.quiz-progress-bar{height:4px;background:var(--bg-overlay);border-radius:2px;overflow:hidden;}
.quiz-progress-fill{height:100%;background:var(--coral);border-radius:2px;transition:width .4s;}
.quiz-progress-text{font-size:11px;color:var(--text-muted);margin-top:6px;}

.q-card{background:var(--bg-base);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:20px;margin-bottom:14px;transition:border-color .2s;}
.q-card:hover{border-color:var(--border-default);}
.q-type{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;}
.q-type.mcq{background:var(--blue-subtle);color:var(--blue);}
.q-type.bug{background:var(--red-subtle);color:var(--red);}
.q-type.fill{background:var(--green-subtle);color:var(--green);}
.q-type.tf{background:var(--purple-subtle);color:var(--purple);}
.q-text{font-size:14px;font-weight:600;margin-bottom:12px;line-height:1.5;color:var(--text-primary);}
.q-code{
  background:var(--bg-raised);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);
  padding:12px 16px;margin-bottom:14px;font-family:var(--font-mono);font-size:12px;
  line-height:1.6;overflow-x:auto;white-space:pre;color:var(--text-primary);
}
.q-options{display:flex;flex-direction:column;gap:6px;margin-bottom:12px;}
.q-option{
  display:flex;align-items:flex-start;gap:10px;padding:10px 14px;border:1.5px solid var(--border-subtle);
  border-radius:var(--radius-sm);cursor:pointer;transition:all .12s;font-size:13px;line-height:1.5;color:var(--text-secondary);
}
.q-option:hover{border-color:var(--coral-dim);background:var(--coral-subtle);color:var(--text-primary);}
.q-option.selected{border-color:var(--coral);background:var(--coral-subtle);color:var(--coral);}
.q-option.correct{border-color:var(--green);background:var(--green-subtle);color:var(--green);}
.q-option.incorrect{border-color:var(--red);background:var(--red-subtle);color:var(--red);}
.q-option.disabled{cursor:default;opacity:.7;}
.q-option.disabled:hover{border-color:var(--border-subtle);background:transparent;color:var(--text-secondary);}
.q-option.disabled.correct{opacity:1;}
.q-marker{
  width:22px;height:22px;border-radius:50%;border:2px solid var(--border-default);flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;margin-top:1px;
}
.q-option.selected .q-marker{border-color:var(--coral);background:var(--coral);color:#000;}
.q-option.correct .q-marker{border-color:var(--green);background:var(--green);color:#fff;}
.q-option.incorrect .q-marker{border-color:var(--red);background:var(--red);color:#fff;}

.q-tf{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;}
.q-tf-btn{
  padding:12px;border:1.5px solid var(--border-subtle);border-radius:var(--radius-sm);cursor:pointer;
  text-align:center;font-size:14px;font-weight:600;transition:all .12s;color:var(--text-secondary);
}
.q-tf-btn:hover{border-color:var(--coral-dim);color:var(--text-primary);}
.q-tf-btn.selected{border-color:var(--coral);background:var(--coral-subtle);color:var(--coral);}
.q-tf-btn.correct{border-color:var(--green);background:var(--green-subtle);color:var(--green);}
.q-tf-btn.incorrect{border-color:var(--red);background:var(--red-subtle);color:var(--red);}
.q-tf-btn.disabled{cursor:default;}

.q-fill{
  width:100%;padding:10px 14px;background:var(--bg-base);border:1.5px solid var(--border-subtle);
  border-radius:var(--radius-sm);color:var(--text-primary);font-family:var(--font-mono);
  font-size:13px;outline:none;margin-bottom:10px;
}
.q-fill:focus{border-color:var(--coral);}
.q-fill.correct{border-color:var(--green);background:var(--green-subtle);}
.q-fill.incorrect{border-color:var(--red);background:var(--red-subtle);}

.q-explain{
  margin-top:10px;padding:12px 16px;background:var(--bg-raised);border:1px solid var(--border-subtle);
  border-radius:var(--radius-sm);font-size:13px;line-height:1.6;color:var(--text-secondary);display:none;
}
.q-explain.show{display:block;}
.q-explain strong{color:var(--text-primary);}

.q-submit-btn{
  width:100%;padding:12px;background:var(--coral);border:none;border-radius:var(--radius-sm);
  color:#000;font-size:14px;font-weight:700;cursor:pointer;transition:all .15s;font-family:var(--font-sans);
}
.q-submit-btn:hover{background:var(--coral-dim);}
.q-submit-btn:disabled{opacity:.35;cursor:not-allowed;}

.q-score{
  background:var(--bg-base);border:2px solid var(--border-default);border-radius:var(--radius-lg);
  padding:28px;text-align:center;margin-bottom:20px;
}
.q-score .score-val{font-size:44px;font-weight:800;margin:8px 0;}
.q-score .score-val.perfect{color:var(--green);}
.q-score .score-val.good{color:var(--coral);}
.q-score .score-val.low{color:var(--red);}
.q-score .score-label{font-size:13px;color:var(--text-muted);}
.q-score .score-xp{font-size:14px;font-weight:700;color:var(--coral);margin-top:8px;}
.q-retry{
  margin-top:12px;padding:10px 24px;background:var(--bg-overlay);border:1px solid var(--border-default);
  border-radius:var(--radius-sm);color:var(--text-primary);font-size:13px;font-weight:600;cursor:pointer;
  font-family:var(--font-sans);
}
.q-retry:hover{background:var(--bg-hover);}

/* ===== SEARCH OVERLAY ===== */
.search-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:300;display:none;align-items:flex-start;justify-content:center;padding-top:80px;backdrop-filter:blur(4px);}
.search-overlay.active{display:flex;}
.search-modal{background:var(--bg-surface);border:1px solid var(--border-default);border-radius:var(--radius-lg);width:560px;max-height:480px;overflow:hidden;box-shadow:var(--shadow-lg);}
.search-modal-input{width:100%;padding:16px 20px;background:transparent;border:none;border-bottom:1px solid var(--border-subtle);color:var(--text-primary);font-size:15px;outline:none;font-family:var(--font-sans);}
.search-results{max-height:380px;overflow-y:auto;padding:8px;}
.search-result-item{padding:10px 14px;border-radius:var(--radius-sm);cursor:pointer;transition:background .12s;}
.search-result-item:hover{background:var(--bg-hover);}
.search-result-item .sr-title{font-size:14px;font-weight:600;}
.search-result-item .sr-module{font-size:12px;color:var(--text-muted);}
.search-result-item .sr-snippet{font-size:13px;color:var(--text-secondary);margin-top:2px;}
.search-result-item .sr-snippet mark{background:var(--coral-subtle);color:var(--coral);padding:1px 2px;border-radius:2px;}

/* ===== XP TOAST ===== */
.xp-toast{
  position:fixed;top:60px;right:20px;background:var(--bg-raised);border:1px solid var(--coral-dim);
  border-radius:var(--radius-md);padding:12px 20px;display:flex;align-items:center;gap:8px;
  font-size:14px;font-weight:700;color:var(--coral);z-index:400;opacity:0;transform:translateY(-10px);
  transition:all .3s;pointer-events:none;box-shadow:var(--shadow-md);
}
.xp-toast.show{opacity:1;transform:translateY(0);}

/* ===== MOBILE ===== */
.sidebar-toggle{display:none;background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:18px;padding:4px;}
@media(max-width:1100px){
  .pane-lab{width:50%;min-width:300px;}
}
@media(max-width:900px){
  .sidebar{transform:translateX(calc(-1*var(--sidebar-w)));}
  .sidebar.open{transform:translateX(0);}
  .app-body{left:0;}
  .sidebar-toggle{display:block;}
  .split-view{flex-direction:column;}
  .pane-lab{width:100%;min-width:0;max-width:none;border-top:1px solid var(--border-subtle);border-left:none;max-height:50%;}
  .pane-lesson{border-right:none;}
  .dash-stats{grid-template-columns:repeat(2,1fr);}
  .dash-modules{grid-template-columns:1fr;}
  .search-trigger span{display:none;}
}
@media(max-width:600px){
  .topbar-stat.streak,.topbar-stat.progress{display:none;}
  .lesson-wrap{padding:24px 16px 60px;}
  .dashboard{padding:24px 16px;}
}
</style>
</head>
<body>

<!-- TOP BAR -->
<header class="topbar">
  <button class="sidebar-toggle" id="sidebar-toggle" onclick="toggleSidebar()">&#9776;</button>
  <div class="topbar-brand" onclick="showDashboard()">
    <div class="logo">B</div>
    <div class="name">Backend Mastery</div>
  </div>
  <div class="topbar-nav" id="topbar-nav">
    <div class="topbar-dropdown" id="dd-module" onclick="toggleDropdown('module')">
      <span class="dd-text" id="dd-module-text">Select Module</span>
      <span class="dd-arrow">&#x25BC;</span>
      <div class="dd-menu" id="dd-module-menu"></div>
    </div>
    <span class="dd-sep">/</span>
    <div class="topbar-dropdown" id="dd-lesson" onclick="toggleDropdown('lesson')">
      <span class="dd-text" id="dd-lesson-text">Select Lesson</span>
      <span class="dd-arrow">&#x25BC;</span>
      <div class="dd-menu" id="dd-lesson-menu"></div>
    </div>
  </div>
  <div class="topbar-right">
    <div class="topbar-stat xp"><span class="stat-icon">&#x2B50;</span><span id="xp-display">0 XP</span></div>
    <div class="topbar-stat streak"><span class="stat-icon">&#x1F525;</span><span id="streak-display">0</span></div>
    <div class="topbar-stat progress"><span class="stat-icon">&#x2705;</span><span id="progress-display">0/19</span></div>
    <div class="search-trigger" onclick="openSearch()"><span>Search</span><kbd>&#8984;K</kbd></div>
    <div class="topbar-avatar" title="Muneer">M</div>
  </div>
</header>

<!-- SIDEBAR -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-scroll" id="sidebar-scroll"></div>
</aside>

<!-- SEARCH OVERLAY -->
<div class="search-overlay" id="search-overlay">
  <div class="search-modal">
    <input type="text" class="search-modal-input" id="search-input" placeholder="Search lessons, patterns, concepts...">
    <div class="search-results" id="search-results"></div>
  </div>
</div>

<!-- XP TOAST -->
<div class="xp-toast" id="xp-toast">+25 XP</div>

<!-- MAIN BODY -->
<div class="app-body" id="app-body">
  <div id="content-area" class="dash-wrap"></div>
</div>

<script>
const COURSE_DATA = ''' + course_json + r''';
const QUIZ_DATA = ''' + quiz_json + r''';
const TOTAL_LESSONS = COURSE_DATA.modules.reduce((s,m)=>s+m.lessons.length,0);
const MODULE_ICONS = ['&#x1F4D0;','&#x2699;','&#x1F310;','&#x1F680;'];

let state = {
  view:'dashboard',
  currentModule:null,
  currentLesson:null,
  completed:{},
  expandedModules:{},
  quizAnswers:{},
  quizSubmitted:{},
  labCollapsed:false,
  xp:0,
  streak:0,
  bestScores:{},
  sidebarOpen:window.innerWidth>900
};

function init(){
  renderSidebar();
  renderDashboard();
  updateTopbar();
  document.addEventListener('keydown',e=>{
    if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();openSearch();}
    if(e.key==='Escape')closeSearch();
    if(e.altKey&&e.key==='ArrowRight')navigateNext();
    if(e.altKey&&e.key==='ArrowLeft')navigatePrev();
  });
  document.addEventListener('click',e=>{
    if(!e.target.closest('.topbar-dropdown')){closeAllDropdowns();}
  });
  if(window.innerWidth<=900){state.sidebarOpen=false;document.getElementById('sidebar').classList.add('collapsed');}
}

// ========== SIDEBAR ==========
function renderSidebar(){
  let h='<div class="lesson-item" style="padding-left:16px;margin-bottom:8px" onclick="showDashboard()"><span style="font-size:16px;flex-shrink:0">&#x1F3E0;</span><span class="l-title" style="font-weight:600">Dashboard</span></div>';
  COURSE_DATA.modules.forEach((mod,mi)=>{
    const exp=state.expandedModules[mod.id];
    const done=mod.lessons.filter(l=>state.completed[mod.id+'/'+l.id]).length;
    h+='<div class="module-group"><div class="module-header'+(exp?' expanded':'')+'" onclick="toggleModule(\''+mod.id+'\')">';
    h+='<span class="m-chevron">&#x25B6;</span>';
    h+='<span>'+mod.title+'</span>';
    h+='<span class="m-progress">'+done+'/'+mod.lessons.length+'</span>';
    h+='</div><div class="module-lessons'+(exp?' show':'')+'">';
    mod.lessons.forEach((l,li)=>{
      const k=mod.id+'/'+l.id;
      const isA=state.currentModule===mod.id&&state.currentLesson===l.id;
      const isC=state.completed[k];
      h+='<div class="lesson-item'+(isA?' active':'')+'" onclick="openLesson(\''+mod.id+'\',\''+l.id+'\')">';
      h+='<div class="l-num'+(isC?' done':'')+'">'+(isC?'&#x2713;':(li+1))+'</div>';
      h+='<span class="l-title">'+l.title+'</span>';
      h+='<span class="l-time">'+l.readTime+'m</span></div>';
    });
    h+='</div></div>';
  });
  document.getElementById('sidebar-scroll').innerHTML=h;
}

function toggleModule(id){state.expandedModules[id]=!state.expandedModules[id];renderSidebar();}
function toggleSidebar(){
  state.sidebarOpen=!state.sidebarOpen;
  document.getElementById('sidebar').classList.toggle('collapsed',!state.sidebarOpen);
  document.getElementById('sidebar').classList.toggle('open',state.sidebarOpen);
  document.getElementById('app-body').classList.toggle('sidebar-collapsed',!state.sidebarOpen);
}

// ========== TOPBAR ==========
function updateTopbar(){
  let done=0;
  COURSE_DATA.modules.forEach(m=>m.lessons.forEach(l=>{if(state.completed[m.id+'/'+l.id])done++;}));
  document.getElementById('xp-display').textContent=state.xp+' XP';
  document.getElementById('streak-display').textContent=state.streak;
  document.getElementById('progress-display').textContent=done+'/'+TOTAL_LESSONS;
  // Update dropdowns
  if(state.currentModule){
    const mod=COURSE_DATA.modules.find(m=>m.id===state.currentModule);
    const lesson=mod?mod.lessons.find(l=>l.id===state.currentLesson):null;
    document.getElementById('dd-module-text').textContent=mod?mod.title:'Select Module';
    document.getElementById('dd-lesson-text').textContent=lesson?lesson.title:'Select Lesson';
  }else{
    document.getElementById('dd-module-text').textContent='Select Module';
    document.getElementById('dd-lesson-text').textContent='Select Lesson';
  }
}

function toggleDropdown(type){
  const el=document.getElementById('dd-'+type);
  const menu=document.getElementById('dd-'+type+'-menu');
  const wasActive=el.classList.contains('active');
  closeAllDropdowns();
  if(wasActive)return;
  el.classList.add('active');
  if(type==='module'){
    let h='';
    COURSE_DATA.modules.forEach((mod,i)=>{
      const done=mod.lessons.filter(l=>state.completed[mod.id+'/'+l.id]).length;
      const isActive=state.currentModule===mod.id;
      h+='<div class="dd-item'+(isActive?' active':'')+'" onclick="event.stopPropagation();selectModuleDD(\''+mod.id+'\')">';
      h+='<span style="font-size:16px">'+MODULE_ICONS[i]+'</span>';
      h+='<span class="dd-label">'+mod.title+'</span>';
      h+='<span class="dd-meta">'+done+'/'+mod.lessons.length+'</span></div>';
    });
    menu.innerHTML=h;
  }else if(type==='lesson'){
    const mod=COURSE_DATA.modules.find(m=>m.id===state.currentModule);
    if(!mod){menu.innerHTML='<div style="padding:12px;color:var(--text-muted);font-size:13px">Select a module first</div>';menu.classList.add('show');return;}
    let h='';
    mod.lessons.forEach((l,i)=>{
      const k=mod.id+'/'+l.id;
      const isC=state.completed[k];
      const isA=state.currentLesson===l.id;
      h+='<div class="dd-item'+(isA?' active':'')+(isC?' completed':'')+'" onclick="event.stopPropagation();openLesson(\''+mod.id+'\',\''+l.id+'\');closeAllDropdowns()">';
      h+='<div class="dd-check">'+(isC?'&#x2713;':'')+'</div>';
      h+='<span class="dd-label">'+l.title+'</span>';
      h+='<span class="dd-meta">'+l.readTime+'m</span></div>';
    });
    menu.innerHTML=h;
  }
  menu.classList.add('show');
}
function selectModuleDD(mid){
  const mod=COURSE_DATA.modules.find(m=>m.id===mid);
  if(mod&&mod.lessons.length)openLesson(mid,mod.lessons[0].id);
  closeAllDropdowns();
}
function closeAllDropdowns(){
  document.querySelectorAll('.topbar-dropdown').forEach(d=>d.classList.remove('active'));
  document.querySelectorAll('.dd-menu').forEach(m=>m.classList.remove('show'));
}

// ========== DASHBOARD ==========
function showDashboard(){
  state.view='dashboard';state.currentModule=null;state.currentLesson=null;
  renderDashboard();renderSidebar();updateTopbar();
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('content-area').className='dash-wrap';
}

function renderDashboard(){
  let tl=0,cl=0,tt=0,tq=0;
  COURSE_DATA.modules.forEach(m=>m.lessons.forEach(l=>{tl++;tt+=l.readTime;tq+=l.interviewQuestions;if(state.completed[m.id+'/'+l.id])cl++;}));
  let h='<div class="dashboard">';
  h+='<div class="dash-greeting"><h1><span class="wave">&#x1F44B;</span> Welcome back, Muneer</h1>';
  h+='<p>'+COURSE_DATA.course.subtitle+'</p></div>';

  h+='<div class="dash-stats">';
  h+='<div class="dash-stat-card"><div class="s-label">Lessons Done</div><div class="s-value green">'+cl+'/'+tl+'</div><div class="s-sub">'+(tl-cl)+' remaining</div></div>';
  h+='<div class="dash-stat-card"><div class="s-label">Total XP</div><div class="s-value gold">'+state.xp+'</div><div class="s-sub">Keep learning to earn more</div></div>';
  h+='<div class="dash-stat-card"><div class="s-label">Interview Qs</div><div class="s-value purple">'+tq+'</div><div class="s-sub">Across all lessons</div></div>';
  h+='<div class="dash-stat-card"><div class="s-label">Lab Questions</div><div class="s-value blue">''' + str(total_qs) + r'''</div><div class="s-sub">Test your knowledge</div></div>';
  h+='</div>';

  h+='<div class="dash-modules">';
  COURSE_DATA.modules.forEach((mod,i)=>{
    const dn=mod.lessons.filter(l=>state.completed[mod.id+'/'+l.id]).length;
    const p=mod.lessons.length?Math.round(dn/mod.lessons.length*100):0;
    const tm=mod.lessons.reduce((s,l)=>s+l.readTime,0);
    h+='<div class="dash-mod-card" onclick="openFirstLesson(\''+mod.id+'\')">';
    h+='<div class="mc-icon mod'+i+'">'+MODULE_ICONS[i]+'</div>';
    h+='<h3>'+mod.title+'</h3>';
    h+='<p>'+mod.description+'</p>';
    h+='<div class="mc-footer"><span>'+mod.lessons.length+' lessons &middot; ~'+tm+' min</span><span style="font-weight:600;color:'+(p===100?'var(--green)':'var(--text-secondary)')+'">'+p+'%</span></div>';
    h+='<div class="mc-bar"><div class="mc-bar-fill" style="width:'+p+'%"></div></div></div>';
  });
  h+='</div></div>';
  document.getElementById('content-area').innerHTML=h;
}

function openFirstLesson(mid){const m=COURSE_DATA.modules.find(x=>x.id===mid);if(m&&m.lessons.length)openLesson(mid,m.lessons[0].id);}

// ========== LESSON VIEW ==========
function openLesson(mid,lid){
  state.view='lesson';state.currentModule=mid;state.currentLesson=lid;state.expandedModules[mid]=true;
  const mod=COURSE_DATA.modules.find(m=>m.id===mid);
  const lesson=mod.lessons.find(l=>l.id===lid);
  const qk=mid+'/'+lid;
  const quizzes=QUIZ_DATA[qk]||[];

  let rendered=marked.parse(lesson.content);
  rendered=rendered.replace(/<h2([^>]*)>Interview Corner<\/h2>/gi,'<div class="interview-corner"><h2$1>&#x1F3AF; Interview Corner</h2>');
  rendered=rendered.replace(/<h2([^>]*)>Exercise<\/h2>/gi,'<div class="exercise-section"><h2$1>&#x1F4BB; Exercise</h2>');
  rendered=closeSpecialSections(rendered);

  const isComp=state.completed[qk];

  // Build split view
  let h='<div class="split-view">';

  // LEFT: lesson pane
  h+='<div class="pane-lesson" id="pane-lesson" style="position:relative">';
  h+='<div class="lesson-wrap">';
  h+='<div class="lesson-head"><h1>'+lesson.title+'</h1>';
  h+='<div class="lesson-badges">';
  h+='<span class="lbadge time">&#x1F552; '+lesson.readTime+' min</span>';
  if(lesson.exercises>0)h+='<span class="lbadge exercise">&#x1F4BB; '+lesson.exercises+' exercise'+(lesson.exercises>1?'s':'')+'</span>';
  if(lesson.interviewQuestions>0)h+='<span class="lbadge interview">&#x1F3AF; '+lesson.interviewQuestions+' interview Q'+(lesson.interviewQuestions>1?'s':'')+'</span>';
  if(quizzes.length>0)h+='<span class="lbadge lab">&#x1F9EA; '+quizzes.length+' lab Q'+(quizzes.length>1?'s':'')+'</span>';
  h+='</div></div>';
  h+='<div class="lesson-body">'+rendered+'</div>';

  // Complete bar
  h+='<div class="lesson-complete-bar">';
  h+='<span>'+(isComp?'&#x2705; Lesson completed &mdash; +25 XP earned':'Finished reading? Mark complete to earn XP')+'</span>';
  h+='<button class="nav-btn'+(isComp?'':' primary')+'" onclick="toggleComplete(\''+qk+'\');openLesson(\''+mid+'\',\''+lid+'\')">'+(isComp?'Undo':'Complete +25 XP')+'</button></div>';

  // Nav
  const nav=getLessonNav(mid,lid);
  h+='<div class="lesson-nav-footer">';
  if(nav.prev)h+='<button class="nav-btn" onclick="openLesson(\''+nav.prev.modId+'\',\''+nav.prev.lessonId+'\')">&#x2190; '+nav.prev.title+'</button>';
  else h+='<div></div>';
  if(nav.next)h+='<button class="nav-btn primary" onclick="openLesson(\''+nav.next.modId+'\',\''+nav.next.lessonId+'\')">'+nav.next.title+' &#x2192;</button>';
  h+='</div></div></div>';

  // RIGHT: lab pane (always present — has playground even without quizzes)
  const hasQuiz = quizzes.length > 0;
  const labCollapsed = state.labCollapsed || false;

  // Toggle button on lesson pane
  h+='<div class="lab-toggle on-lesson" id="lab-toggle-lesson" onclick="toggleLabPane()" title="'+(labCollapsed?'Open Lab':'')+'">&#x1F9EA;</div>';

  h+='<div class="pane-lab'+(labCollapsed?' collapsed':'')+'" id="pane-lab">';
  h+='<div class="lab-header"><span style="font-size:18px">&#x1F9EA;</span><h3>Lab</h3>';
  if(hasQuiz) h+='<span class="lab-count">'+quizzes.length+' Q</span>';
  h+='<button class="lab-close" onclick="toggleLabPane()" title="Minimize lab">&#x2715;</button></div>';

  // Lab tabs
  h+='<div class="lab-tabs">';
  if(hasQuiz) h+='<div class="lab-tab active" onclick="switchLabTab(\'quiz\',this)">&#x1F9EA; Quiz</div>';
  h+='<div class="lab-tab'+(hasQuiz?'':' active')+'" onclick="switchLabTab(\'playground\',this)">&#x25B6; Go Playground</div>';
  h+='</div>';

  // Quiz panel
  if(hasQuiz){
    h+='<div class="lab-panel active" id="lab-panel-quiz">';
    h+='<div class="lab-body" id="lab-body">';
    h+=renderQuiz(mid,lid,quizzes);
    h+='</div></div>';
  }

  // Go Playground panel
  h+='<div class="lab-panel'+(hasQuiz?'':' active')+'" id="lab-panel-playground">';
  h+='<div class="playground-wrap">';
  h+='<div class="pg-editor-wrap">';
  h+='<textarea class="pg-editor" id="pg-editor" spellcheck="false">package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Println(\"Hello, Go!\")\n}</textarea>';
  h+='</div>';
  h+='<div class="pg-toolbar">';
  h+='<button class="pg-run-btn" id="pg-run-btn" onclick="runGoCode()"><span id="pg-run-icon">&#x25B6;</span> Run</button>';
  h+='<button class="pg-fmt-btn" onclick="formatGoCode()">Format</button>';
  h+='<span class="pg-status" id="pg-status">Ready</span>';
  h+='</div>';
  h+='<div class="pg-output-wrap"><div class="pg-output" id="pg-output"><span class="pg-placeholder">Output will appear here...</span></div></div>';
  h+='</div></div>';

  h+='</div>'; // close pane-lab
  h+='</div>'; // close split-view

  document.getElementById('content-area').className='';
  document.getElementById('content-area').innerHTML=h;
  document.getElementById('sidebar').classList.remove('open');
  renderSidebar();
  updateTopbar();

  // Handle tab key in playground editor
  const pgEditor = document.getElementById('pg-editor');
  if(pgEditor){
    pgEditor.addEventListener('keydown', function(e){
      if(e.key==='Tab'){
        e.preventDefault();
        const start=this.selectionStart,end=this.selectionEnd;
        this.value=this.value.substring(0,start)+'\t'+this.value.substring(end);
        this.selectionStart=this.selectionEnd=start+1;
      }
      if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();runGoCode();}
    });
  }

  // Highlight code blocks & wrap Go blocks in Jupyter-style code cells
  let cellId=0;
  document.querySelectorAll('.lesson-body pre code').forEach(block=>{
    hljs.highlightElement(block);
    const pre=block.parentElement;
    const lang=(block.className.match(/language-(\w+)/)||[])[1]||'';
    const code=block.textContent;
    const isGo=lang==='go'||lang==='golang';
    // Check if this looks like a runnable Go program (has package and func main)
    const isRunnable=isGo&&/package\s+main/.test(code)&&/func\s+main/.test(code);

    if(isGo){
      // Wrap in code-cell container
      const cell=document.createElement('div');
      cell.className='code-cell'+(isRunnable?'':' no-output');
      cell.id='code-cell-'+cellId;
      pre.parentNode.insertBefore(cell,pre);
      cell.appendChild(pre);

      // Add copy button on pre
      const copyBtn=document.createElement('button');
      copyBtn.className='copy-btn';copyBtn.textContent='Copy';
      copyBtn.onclick=()=>{navigator.clipboard.writeText(code).then(()=>{copyBtn.textContent='Copied!';setTimeout(()=>copyBtn.textContent='Copy',1500);});};
      pre.appendChild(copyBtn);

      // Toolbar
      const toolbar=document.createElement('div');
      toolbar.className='code-cell-toolbar';

      if(isRunnable){
        const runBtn=document.createElement('button');
        runBtn.className='cc-btn cc-run';
        runBtn.id='cc-run-'+cellId;
        runBtn.innerHTML='&#x25B6; Run';
        const cid=cellId;
        runBtn.onclick=()=>runCodeCell(cid,code);
        toolbar.appendChild(runBtn);
      }

      const editBtn=document.createElement('button');
      editBtn.className='cc-btn';
      editBtn.innerHTML='&#x270E; Edit in Playground';
      editBtn.onclick=()=>openInPlayground(code);
      toolbar.appendChild(editBtn);

      const langLabel=document.createElement('span');
      langLabel.className='cc-lang';
      langLabel.textContent=isRunnable?'Go (runnable)':'Go';
      toolbar.appendChild(langLabel);

      cell.appendChild(toolbar);

      // Output area (for runnable code)
      if(isRunnable){
        const output=document.createElement('div');
        output.className='code-cell-output';
        output.id='cc-output-'+cellId;
        cell.appendChild(output);
      }

      cellId++;
    } else {
      // Non-Go: just add copy button
      const copyBtn=document.createElement('button');
      copyBtn.className='copy-btn';copyBtn.textContent='Copy';
      copyBtn.onclick=()=>{navigator.clipboard.writeText(code).then(()=>{copyBtn.textContent='Copied!';setTimeout(()=>copyBtn.textContent='Copy',1500);});};
      pre.appendChild(copyBtn);
    }
  });
}

// ========== QUIZ ENGINE ==========
function renderQuiz(mid,lid,quizzes){
  const qk=mid+'/'+lid;
  const submitted=state.quizSubmitted[qk];
  const answers=state.quizAnswers[qk]||{};
  const answered=Object.keys(answers).length;

  let h='';

  // Progress bar
  h+='<div class="quiz-progress-wrap">';
  h+='<div class="quiz-progress-bar"><div class="quiz-progress-fill" style="width:'+(quizzes.length?Math.round(answered/quizzes.length*100):0)+'%"></div></div>';
  h+='<div class="quiz-progress-text">'+answered+' of '+quizzes.length+' answered</div></div>';

  if(submitted){
    const score=calculateScore(qk,quizzes);
    const pct=Math.round(score/quizzes.length*100);
    const cls=pct===100?'perfect':pct>=60?'good':'low';
    const xpEarned=score*10;
    h+='<div class="q-score">';
    h+='<div class="score-label">Your Score</div>';
    h+='<div class="score-val '+cls+'">'+score+'/'+quizzes.length+'</div>';
    h+='<div class="score-label">'+(pct===100?'Perfect! You own this.':pct>=80?'Great work! Review explanations below.':pct>=60?'Good start. Check the explanations.':'Needs work. Re-read and retry.')+'</div>';
    h+='<div class="score-xp">+'+xpEarned+' XP earned</div>';
    h+='<button class="q-retry" onclick="retryQuiz(\''+mid+'\',\''+lid+'\')">&#x1F504; Retry</button>';
    h+='</div>';
  }

  quizzes.forEach((q,i)=>{
    h+='<div class="q-card" id="quiz-q-'+i+'">';
    const typeLabels={mcq:'Multiple Choice',bug:'Spot the Bug',fill:'Code Completion',tf:'True / False'};
    h+='<div class="q-type '+q.type+'">'+typeLabels[q.type]+'</div>';
    h+='<div class="q-text">'+escapeHtml(q.question)+'</div>';

    if(q.code){h+='<div class="q-code">'+escapeHtml(q.code)+'</div>';}

    if(q.type==='mcq'||q.type==='bug'){
      h+='<div class="q-options">';
      q.options.forEach((opt,j)=>{
        let cls='q-option';
        if(submitted){cls+=' disabled';if(j===q.correct)cls+=' correct';else if(answers[i]===j)cls+=' incorrect';}
        else if(answers[i]===j)cls+=' selected';
        h+='<div class="'+cls+'" onclick="'+(submitted?'':'selectAnswer(\''+qk+'\','+i+','+j+')')+'">';
        h+='<div class="q-marker">'+String.fromCharCode(65+j)+'</div>';
        h+='<span>'+escapeHtml(opt)+'</span></div>';
      });
      h+='</div>';
    }else if(q.type==='tf'){
      h+='<div class="q-tf">';
      [true,false].forEach(val=>{
        let cls='q-tf-btn';
        if(submitted){cls+=' disabled';if(val===q.correct)cls+=' correct';else if(answers[i]===val)cls+=' incorrect';}
        else if(answers[i]===val)cls+=' selected';
        h+='<div class="'+cls+'" onclick="'+(submitted?'':'selectAnswer(\''+qk+'\','+i+','+(val?'true':'false')+')')+'">'+
          (val?'&#x2705; True':'&#x274C; False')+'</div>';
      });
      h+='</div>';
    }else if(q.type==='fill'){
      let cls='q-fill';
      if(submitted){const ua=(answers[i]||'').trim().toLowerCase();cls+=ua===q.answer.toLowerCase()?' correct':' incorrect';}
      h+='<input type="text" class="'+cls+'" placeholder="Type your answer..." value="'+escapeHtml(answers[i]||'')+'" '+(submitted?'disabled':'')+
        ' oninput="fillAnswer(\''+qk+'\','+i+',this.value)" onkeydown="if(event.key===\'Enter\')submitQuiz(\''+mid+'\',\''+lid+'\')">';
      if(submitted){const ua=(answers[i]||'').trim().toLowerCase();if(ua!==q.answer.toLowerCase())h+='<div style="font-size:12px;color:var(--green);margin-bottom:6px">Answer: <code style="color:var(--green);font-family:var(--font-mono)">'+escapeHtml(q.answer)+'</code></div>';}
    }

    h+='<div class="q-explain'+(submitted?' show':'')+'">';
    h+='<strong>&#x1F4A1; </strong>'+escapeHtml(q.explanation)+'</div></div>';
  });

  if(!submitted){
    const allAnswered=quizzes.every((_,i)=>answers[i]!==undefined&&answers[i]!=='');
    h+='<button class="q-submit-btn" onclick="submitQuiz(\''+mid+'\',\''+lid+'\')"'+(allAnswered?'':' disabled')+'>Check Answers</button>';
  }
  return h;
}

function selectAnswer(qk,qi,val){
  if(!state.quizAnswers[qk])state.quizAnswers[qk]={};
  state.quizAnswers[qk][qi]=val;
  const parts=qk.split('/');
  const mid=parts[0];
  const lid=parts.slice(1).join('/');
  const quizzes=QUIZ_DATA[qk]||[];
  document.getElementById('lab-body').innerHTML=renderQuiz(mid,lid,quizzes);
}

function fillAnswer(qk,qi,val){
  if(!state.quizAnswers[qk])state.quizAnswers[qk]={};
  state.quizAnswers[qk][qi]=val;
  const quizzes=QUIZ_DATA[qk]||[];
  const answers=state.quizAnswers[qk];
  const allAnswered=quizzes.every((_,i)=>answers[i]!==undefined&&answers[i]!=='');
  const btn=document.querySelector('.q-submit-btn');
  if(btn)btn.disabled=!allAnswered;
}

function submitQuiz(mid,lid){
  const qk=mid+'/'+lid;
  state.quizSubmitted[qk]=true;
  const quizzes=QUIZ_DATA[qk]||[];
  const score=calculateScore(qk,quizzes);
  const xpEarned=score*10;
  const prevBest=state.bestScores[qk]||0;
  const prevXP=prevBest*10;
  const netXP=Math.max(0,xpEarned-prevXP);
  if(score>prevBest)state.bestScores[qk]=score;
  state.xp+=netXP;
  if(netXP>0)showXPToast('+'+netXP+' XP');
  document.getElementById('lab-body').innerHTML=renderQuiz(mid,lid,quizzes);
  document.getElementById('lab-body').scrollTop=0;
  updateTopbar();
}

function retryQuiz(mid,lid){
  const qk=mid+'/'+lid;
  delete state.quizAnswers[qk];
  delete state.quizSubmitted[qk];
  const quizzes=QUIZ_DATA[qk]||[];
  document.getElementById('lab-body').innerHTML=renderQuiz(mid,lid,quizzes);
}

function calculateScore(qk,quizzes){
  const answers=state.quizAnswers[qk]||{};
  let score=0;
  quizzes.forEach((q,i)=>{
    if(q.type==='fill'){if((answers[i]||'').trim().toLowerCase()===q.answer.toLowerCase())score++;}
    else if(q.type==='tf'){if(answers[i]===q.correct)score++;}
    else{if(answers[i]===q.correct)score++;}
  });
  return score;
}

// ========== INLINE CODE CELL EXECUTION ==========
async function runCodeCell(cellId,code){
  const btn=document.getElementById('cc-run-'+cellId);
  const output=document.getElementById('cc-output-'+cellId);
  const cell=document.getElementById('code-cell-'+cellId);
  if(!btn||!output)return;

  btn.disabled=true;
  btn.innerHTML='<span class="spinner"></span> Running...';
  output.className='code-cell-output show running';
  output.textContent='Compiling and running...';
  cell.classList.add('has-output');

  try{
    const resp=await fetch('/api/run',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:code})
    });
    const data=await resp.json();

    if(data.error){
      output.className='code-cell-output show error';
      output.textContent=data.error;
      if(data.output){output.textContent=data.output+'\n\n'+data.error;}
    } else {
      output.className='code-cell-output show success';
      output.textContent=data.output||'(no output)';
    }
    if(data.time){output.textContent+='\n\n// '+data.time;}
  }catch(err){
    output.className='code-cell-output show error';
    output.textContent='Server not running. Start the Go server:\n\n  cd server && go run main.go\n\nThen open http://localhost:3000';
  }

  btn.disabled=false;
  btn.innerHTML='&#x25B6; Run';
}

function openInPlayground(code){
  // Open lab panel if collapsed
  if(state.labCollapsed){state.labCollapsed=false;const lab=document.getElementById('pane-lab');if(lab)lab.classList.remove('collapsed');}
  // Switch to playground tab
  const pgTab=document.querySelector('.lab-tab:last-child');
  if(pgTab){switchLabTab('playground',pgTab);}
  // Set editor content
  const editor=document.getElementById('pg-editor');
  if(editor){editor.value=code;editor.focus();}
}

// ========== LAB PANEL TOGGLE ==========
function toggleLabPane(){
  state.labCollapsed=!state.labCollapsed;
  const lab=document.getElementById('pane-lab');
  const toggle=document.getElementById('lab-toggle-lesson');
  if(lab){lab.classList.toggle('collapsed',state.labCollapsed);}
  if(toggle){toggle.title=state.labCollapsed?'Open Lab':'';}
}

function switchLabTab(tab,el){
  document.querySelectorAll('.lab-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.lab-panel').forEach(p=>p.classList.remove('active'));
  const panel=document.getElementById('lab-panel-'+tab);
  if(panel)panel.classList.add('active');
}

// ========== GO PLAYGROUND ==========
async function runGoCode(){
  const editor=document.getElementById('pg-editor');
  const output=document.getElementById('pg-output');
  const btn=document.getElementById('pg-run-btn');
  const icon=document.getElementById('pg-run-icon');
  const status=document.getElementById('pg-status');
  if(!editor)return;

  btn.disabled=true;
  icon.innerHTML='<span class="spinner"></span>';
  status.textContent='Running...';
  output.className='pg-output';
  output.textContent='';

  try{
    const resp=await fetch('/api/run',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:editor.value})
    });
    const data=await resp.json();

    if(data.error){
      output.className='pg-output error';
      output.textContent=data.error;
      if(data.output){output.textContent=data.output+'\n\n'+data.error;}
      status.textContent='Error ('+data.time+')';
    } else {
      output.className='pg-output success';
      output.textContent=data.output||'(no output)';
      status.textContent='Done ('+data.time+')';
    }
  }catch(err){
    output.className='pg-output error';
    output.textContent='Server not running. Start:\n  cd server && go run main.go';
    status.textContent='Disconnected';
  }

  btn.disabled=false;
  icon.innerHTML='&#x25B6;';
}

async function formatGoCode(){
  const editor=document.getElementById('pg-editor');
  const status=document.getElementById('pg-status');
  if(!editor)return;
  status.textContent='Formatting...';
  try{
    const resp=await fetch('/api/format',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:editor.value})
    });
    const data=await resp.json();
    if(data.error){status.textContent='Format error: '+data.error;return;}
    if(data.code){editor.value=data.code;status.textContent='Formatted';}
    else{status.textContent='Already formatted';}
  }catch(err){status.textContent='Server not running';}
}

// ========== XP & GAMIFICATION ==========
function showXPToast(text){
  const el=document.getElementById('xp-toast');
  el.textContent=text;
  el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'),2000);
}

function toggleComplete(k){
  const wasComplete=state.completed[k];
  state.completed[k]=!wasComplete;
  if(!wasComplete){
    state.xp+=25;
    state.streak+=1;
    showXPToast('+25 XP');
  }else{
    state.xp=Math.max(0,state.xp-25);
    state.streak=Math.max(0,state.streak-1);
  }
  renderSidebar();
  updateTopbar();
  if(state.view==='dashboard')renderDashboard();
}

// ========== NAVIGATION ==========
function getLessonNav(mid,lid){
  const all=[];COURSE_DATA.modules.forEach(m=>m.lessons.forEach(l=>all.push({modId:m.id,lessonId:l.id,title:l.title})));
  const idx=all.findIndex(l=>l.modId===mid&&l.lessonId===lid);
  return{prev:idx>0?all[idx-1]:null,next:idx<all.length-1?all[idx+1]:null};
}
function navigateNext(){if(!state.currentModule)return;const n=getLessonNav(state.currentModule,state.currentLesson);if(n.next)openLesson(n.next.modId,n.next.lessonId);}
function navigatePrev(){if(!state.currentModule)return;const n=getLessonNav(state.currentModule,state.currentLesson);if(n.prev)openLesson(n.prev.modId,n.prev.lessonId);}

// ========== SEARCH ==========
function openSearch(){
  document.getElementById('search-overlay').classList.add('active');
  const inp=document.getElementById('search-input');
  inp.value='';inp.focus();inp.oninput=()=>performSearch(inp.value);
}
function closeSearch(){document.getElementById('search-overlay').classList.remove('active');}
document.getElementById('search-overlay').addEventListener('click',e=>{if(e.target===document.getElementById('search-overlay'))closeSearch();});

function performSearch(query){
  const results=document.getElementById('search-results');
  if(!query||query.length<2){results.innerHTML='<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">Type to search across all lessons...</div>';return;}
  const q=query.toLowerCase(),matches=[];
  COURSE_DATA.modules.forEach(mod=>mod.lessons.forEach(lesson=>{
    const content=lesson.content.toLowerCase(),idx=content.indexOf(q);
    if(idx!==-1||lesson.title.toLowerCase().includes(q)){
      let snippet='';
      if(idx!==-1){const s=Math.max(0,idx-60),e=Math.min(content.length,idx+query.length+60);snippet=lesson.content.substring(s,e).replace(/[#*`\n]/g,' ').trim();const re=new RegExp('('+query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','gi');snippet=snippet.replace(re,'<mark>$1</mark>');if(s>0)snippet='...'+snippet;if(e<content.length)snippet+='...';}
      matches.push({modTitle:mod.title,modId:mod.id,lessonId:lesson.id,title:lesson.title,snippet});
    }
  }));
  if(!matches.length){results.innerHTML='<div style="padding:20px;text-align:center;color:var(--text-muted)">No results found</div>';return;}
  let h='';matches.slice(0,10).forEach(m=>{h+='<div class="search-result-item" onclick="closeSearch();openLesson(\''+m.modId+'\',\''+m.lessonId+'\')"><div class="sr-title">'+m.title+'</div><div class="sr-module">'+m.modTitle+'</div>'+(m.snippet?'<div class="sr-snippet">'+m.snippet+'</div>':'')+'</div>';});
  if(matches.length>10)h+='<div style="padding:10px 14px;font-size:12px;color:var(--text-muted)">+'+(matches.length-10)+' more</div>';
  results.innerHTML=h;
}

// ========== UTILITIES ==========
function escapeHtml(str){
  if(typeof str!=='string')return str;
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function closeSpecialSections(html){
  let result='',inSpecial=false;
  const lines=html.split('\n');
  for(let i=0;i<lines.length;i++){
    const line=lines[i];
    const isOpen=line.includes('class="interview-corner"')||line.includes('class="exercise-section"');
    const isH2=/^<h2/.test(line.trim())&&!isOpen;
    if(inSpecial&&isH2){result+='</div>\n';inSpecial=false;}
    if(isOpen){if(inSpecial)result+='</div>\n';inSpecial=true;}
    result+=line+'\n';
  }
  if(inSpecial)result+='</div>';
  return result;
}

init();
</script>
</body>
</html>'''

output_path = os.path.join(SCRIPT_DIR, "index.html")
with open(output_path, "w") as f:
    f.write(html)

size_kb = os.path.getsize(output_path) // 1024
print(f"Generated LMS v3: {output_path}")
print(f"File size: {size_kb} KB")
