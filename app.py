from flask import Flask, render_template_string, request, jsonify
import requests
import os
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET

app = Flask(__name__)

AVAILABLE_MODELS_CACHE = {}

def get_available_models(api_key):
    if api_key in AVAILABLE_MODELS_CACHE and AVAILABLE_MODELS_CACHE[api_key]:
        return AVAILABLE_MODELS_CACHE[api_key]
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
            timeout=8
        )
        if r.status_code == 200:
            models = r.json().get('models', [])
            valid = [
                m['name'].replace('models/', '') for m in models
                if 'generateContent' in m.get('supportedGenerationMethods', [])
            ]
            prioritized = []
            for keyword in ['3.8-flash', 'flash-lite', '3.5-flash', '3.0-flash', '2.0-flash', 'flash', 'pro']:
                for v in valid:
                    if keyword in v and v not in prioritized and '2.5' not in v and '1.5' not in v:
                        prioritized.append(v)
            for v in valid:
                if v not in prioritized and '2.5' not in v and '1.5' not in v:
                    prioritized.append(v)
            if prioritized:
                AVAILABLE_MODELS_CACHE[api_key] = prioritized
                return prioritized
    except Exception:
        pass
    return ["gemini-3.8-flash", "gemini-3.8-flash-lite", "gemini-3.8-pro"]

def extract_pptx_text(file_stream):
    text_runs = []
    try:
        with zipfile.ZipFile(file_stream) as z:
            slide_files = [f for f in z.namelist() if f.startswith('ppt/slides/slide') and f.endswith('.xml')]
            slide_files.sort(key=lambda x: int(re.search(r'slide(\d+)\.xml', x).group(1)) if re.search(r'slide(\d+)\.xml', x) else 0)
            for idx, slide in enumerate(slide_files, 1):
                xml_content = z.read(slide)
                tree = ET.fromstring(xml_content)
                slide_texts = [elem.text.strip() for elem in tree.iter() if elem.tag.endswith('}t') and elem.text and elem.text.strip()]
                if slide_texts:
                    text_runs.append(f"[Slide {idx}]: " + " | ".join(slide_texts))
    except Exception as e:
        return f"Error reading PPTX: {str(e)}"
    return "\n".join(text_runs)

def parse_filename_metadata(filename):
    meta = {}
    if not filename:
        return meta
    fn = filename.upper()
    lvl = re.search(r'(?:N|NIVEAU|AEP)[_-]?(\d)', fn) or re.search(r'(\d)AEP', fn)
    per = re.search(r'P(\d)', fn)
    uni = re.search(r'U(\d)', fn)
    sem = re.search(r'SEM[_-]?(\d+)', fn) or re.search(r'W(\d+)', fn)
    sea = re.search(r'_S(\d+)', fn) or re.search(r'SEANCE[_-]?(\d+)', fn)
    ncm = re.search(r'NCM[_-]?(\d+)', fn)

    if lvl: meta['level'] = lvl.group(1)
    if per: meta['periode'] = per.group(1)
    if uni: meta['unite'] = uni.group(1)
    if sem: meta['semaine'] = sem.group(1)
    if sea: meta['seance'] = sea.group(1)
    if ncm: meta['ncm'] = ncm.group(1)
    return meta

def call_gemini_api(api_key, parts, json_mode=False, temperature=0.15):
    candidate_models = get_available_models(api_key)
    gen_config = {"temperature": temperature}
    if json_mode:
        gen_config["responseMimeType"] = "application/json"

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": gen_config
    }
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': api_key}
    last_error = ""

    for attempt in range(2):
        for model_name in candidate_models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
                res = requests.post(url, json=payload, headers=headers, timeout=60)
                res_data = res.json()
                if res.status_code == 200 and 'candidates' in res_data:
                    raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
                    return raw_text, None
                else:
                    last_error = res_data.get('error', {}).get('message', 'يرجى المحاولة بعد لحظات')
                    time.sleep(0.6)
                    continue
            except Exception as e:
                last_error = str(e)
                continue
    return None, last_error

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>الأكاديمية الذكية Pro</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                processEscapes: true
            },
            options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre'] }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Cairo', sans-serif; background: #0b1120; color: #f8fafc; margin: 0; overflow-x: hidden; }
        .glass-panel { background: rgba(30, 41, 59, 0.9); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.08); }
        .nav-tab { transition: all 0.2s ease; cursor: pointer; }
        .nav-tab.active { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; border-color: #60a5fa; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4); }

        .sheet-scroll-viewport { width: 100%; overflow-x: auto; padding-bottom: 12px; display: flex; justify-content: center; }
        .ncm-sheet { background: #ffffff; color: #0f172a; border-radius: 14px; padding: 18px 22px; box-shadow: 0 20px 50px rgba(0,0,0,0.55); width: 1120px; min-width: 1120px; max-width: 1120px; margin: 0 auto; position: relative; border: 1px solid #cbd5e1; box-sizing: border-box; }
        .ncm-top-banner { background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%); color: white; border-radius: 12px; padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 10px; border-bottom: 4px solid #f59e0b; }
        .ncm-orange-badge { background: linear-gradient(180deg, #f97316 0%, #ea580c 100%); color: white; border-radius: 10px; padding: 6px 16px; text-align: center; min-width: 95px; box-shadow: 0 3px 10px rgba(0,0,0,0.25); border: 1.5px solid rgba(255,255,255,0.4); flex-shrink: 0; }
        .ncm-objectives-box { background: #f8fafc; border: 1.5px solid #cbd5e1; border-right: 6px solid #2563eb; border-radius: 10px; padding: 9px 16px; margin-bottom: 16px; font-size: 13px; line-height: 1.55; }
        [dir="ltr"] .ncm-objectives-box { border-right: 1.5px solid #cbd5e1; border-left: 6px solid #2563eb; }

        .mindmap-container { position: relative; z-index: 1; width: 100%; padding: 4px 0; }
        #pathSvg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 1; }
        .ncm-grid-layout { position: relative; z-index: 2; display: grid; grid-template-columns: 1fr 250px 1fr; gap: 28px; align-items: center; }

        .station-box { background: #ffffff; border: 2px solid #cbd5e1; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06); display: flex; flex-direction: column; height: auto; }
        .station-header-bar { color: white; padding: 8px 14px; display: flex; align-items: center; justify-content: space-between; gap: 8px; font-weight: 800; font-size: 13.5px; }
        .station-time-tag { background: rgba(0,0,0,0.28); color: white; padding: 2px 10px; border-radius: 999px; font-size: 11.5px; font-weight: 800; border: 1px solid rgba(255,255,255,0.4); white-space: nowrap; flex-shrink: 0; }
        .station-content-body { padding: 11px 14px; font-size: 12.5px; line-height: 1.65; }

        .center-hub-box { display: flex; align-items: center; justify-content: center; padding: 6px; }
        .center-blue-circle { width: 224px; height: 224px; border-radius: 50%; background: radial-gradient(circle at 35% 30%, #2563eb 0%, #1e3a8a 90%); color: white; padding: 15px; text-align: center; border: 5px solid #ffffff; outline: 3px solid #2563eb; box-shadow: 0 10px 28px rgba(37, 99, 235, 0.35); display: flex; flex-direction: column; align-items: center; justify-content: center; position: relative; margin: 0 auto; }

        [contenteditable="true"]:focus { outline: 2px dashed #f59e0b; background: rgba(245, 158, 11, 0.1); border-radius: 4px; }
        .prose-output { line-height: 1.85; font-size: 15px; }
        .prose-output h1, .prose-output h2, .prose-output h3 { color: #38bdf8; font-weight: 800; margin-top: 1.25rem; margin-bottom: 0.6rem; }
        .prose-output p { margin-bottom: 0.85rem; }
        .prose-output ul { list-style-type: disc; padding-inline-start: 1.5rem; }
        .prose-output ol { list-style-type: decimal; padding-inline-start: 1.5rem; }
        .prose-output table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
        .prose-output th, .prose-output td { border: 1px solid #334155; padding: 8px 12px; }
        .prose-output th { background: #1e293b; color: #38bdf8; }
        .prose-output strong { color: #fcd34d; font-weight: 800; }
        mjx-container { overflow-x: auto; overflow-y: hidden; max-width: 100%; padding: 2px 0; }

        @media print {
            @page { size: A4 landscape; margin: 4mm; }
            body { background: white !important; color: black !important; }
            .no-print { display: none !important; }
            .sheet-scroll-viewport { overflow: visible !important; display: block !important; }
            .ncm-sheet { box-shadow: none !important; border: none !important; width: 100% !important; min-width: 100% !important; padding: 2mm 4mm !important; }
        }
    </style>
</head>
<body class="p-3 md:p-6">
    <!-- شريط التنقل المحسن للهواتف -->
    <div class="max-w-6xl mx-auto no-print">
        <header class="flex flex-col md:flex-row items-center justify-between gap-3 mb-5 glass-panel p-4 rounded-2xl">
            <div class="flex items-center gap-3 w-full md:w-auto justify-between">
                <div class="flex items-center gap-2">
                    <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-cyan-500 flex items-center justify-center shadow">
                        <span class="text-lg">🎓</span>
                    </div>
                    <div>
                        <h1 class="text-base font-black text-white">المنصة الذكية <span class="text-cyan-400">Pro</span></h1>
                        <p class="text-[11px] text-slate-400">الخطاطات والمسائل والملخصات والترجمة</p>
                    </div>
                </div>
                <button onclick="toggleApiModal()" class="p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs text-slate-300 md:hidden">⚙️</button>
            </div>

            <!-- أزرار الأقسام المتجاوبة -->
            <div class="grid grid-cols-2 sm:flex items-center gap-2 w-full md:w-auto">
                <button type="button" onclick="switchSection('ncm', this)" class="nav-tab active px-3 py-2 rounded-xl border border-slate-700 bg-slate-800 text-[11px] font-extrabold flex items-center justify-center gap-1">
                    <span>🗺️</span> خطاطات (NCM)
                </button>
                <button type="button" onclick="switchSection('solver', this)" class="nav-tab px-3 py-2 rounded-xl border border-slate-700 bg-slate-800 text-[11px] font-extrabold text-slate-300 flex items-center justify-center gap-1">
                    <span>🧮</span> حل المسائل
                </button>
                <button type="button" onclick="switchSection('summarizer', this)" class="nav-tab px-3 py-2 rounded-xl border border-slate-700 bg-slate-800 text-[11px] font-extrabold text-slate-300 flex items-center justify-center gap-1">
                    <span>📑</span> الملخص الذكي
                </button>
                <button type="button" onclick="switchSection('translator', this)" class="nav-tab px-3 py-2 rounded-xl border border-slate-700 bg-slate-800 text-[11px] font-extrabold text-slate-300 flex items-center justify-center gap-1">
                    <span>🌐</span> الترجمة
                </button>
                <button type="button" onclick="toggleApiModal()" class="hidden md:block p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs text-slate-400">⚙️</button>
            </div>
        </header>

        <div id="apiModal" class="hidden fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
            <div class="glass-panel p-6 rounded-3xl max-w-md w-full border border-blue-500/40">
                <h3 class="text-base font-bold mb-2 text-cyan-400">إعداد مفتاح الخدمة السحابية</h3>
                <input type="password" id="apiKeyInput" placeholder="أدخل المفتاح هنا..." class="w-full p-3 rounded-xl bg-slate-900 border border-slate-700 text-white mb-4 text-left font-mono text-sm" dir="ltr">
                <div class="flex justify-end gap-2">
                    <button onclick="toggleApiModal()" class="px-4 py-2 rounded-xl bg-slate-800 text-xs font-bold">إغلاق</button>
                    <button onclick="saveApiKey()" class="px-5 py-2 rounded-xl bg-blue-600 text-white font-black text-xs">حفظ</button>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== القسم 1: الخطاطات ==================== -->
    <div id="sec-ncm" class="app-section max-w-6xl mx-auto">
        <div class="glass-panel rounded-3xl p-5 shadow-2xl mb-6 no-print">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                <div class="lg:col-span-2">
                    <label class="block text-xs font-bold text-cyan-400 mb-2">1. ارفع ملف الدرس أو الصق محتواه:</label>
                    <div class="flex gap-2 mb-2.5">
                        <label class="flex-1 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-cyan-500/50 rounded-2xl p-3 text-center transition flex items-center justify-center gap-2">
                            <span class="text-lg">📂</span>
                            <span id="ncmFileName" class="text-xs font-bold text-slate-200">اختر ملف (.pptx / .pdf / صورة)</span>
                            <input type="file" id="ncmFileInput" accept=".pptx,.ppt,.pdf,image/*,.txt" class="hidden" onchange="handleNcmFile(this)">
                        </label>
                        <button id="ncmClearBtn" onclick="clearNcmFile()" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="ncmTextInput" rows="3" placeholder="أو الصق نص الدرس هنا..." class="w-full p-3 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs"></textarea>
                </div>

                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-between">
                    <div>
                        <label class="block text-xs font-bold text-cyan-400 mb-2">2. عدد المحطات:</label>
                        <div class="grid grid-cols-5 gap-1.5 mb-3">
                            <button type="button" onclick="setStations(2, this)" class="st-btn py-1.5 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs">2</button>
                            <button type="button" onclick="setStations(3, this)" class="st-btn py-1.5 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs">3</button>
                            <button type="button" onclick="setStations(4, this)" class="st-btn py-1.5 rounded-xl border border-cyan-500 bg-cyan-500/20 text-cyan-300 font-black text-xs">4</button>
                            <button type="button" onclick="setStations(5, this)" class="st-btn py-1.5 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs">5</button>
                            <button type="button" onclick="setStations(6, this)" class="st-btn py-1.5 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs">6</button>
                        </div>
                        <div class="grid grid-cols-3 gap-1.5 mb-2">
                            <input id="metaLevel" type="text" placeholder="المستوى" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaPeriode" type="text" placeholder="المرحلة" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaUnite" type="text" placeholder="الوحدة" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                        </div>
                        <div class="grid grid-cols-3 gap-1.5">
                            <input id="metaSemaine" type="text" placeholder="الأسبوع" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaSeance" type="text" placeholder="الحصة" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="ncmNumInput" type="text" value="10" placeholder="رقم NCM" class="p-1.5 rounded-lg bg-slate-800 border border-amber-500/50 text-center font-black text-[11px] text-amber-300">
                        </div>
                    </div>
                </div>
            </div>

            <button type="button" onclick="generateNCM()" id="ncmGenBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-blue-600 via-indigo-600 to-cyan-600 font-black text-white text-sm shadow-lg">
                <span id="ncmBtnText">توليد الخطاطة الرسمية بالترويسة الكاملة ⚡</span>
            </button>
        </div>

        <div id="printBar" class="hidden mb-3 flex flex-wrap items-center justify-between gap-2 glass-panel px-4 py-2.5 rounded-2xl no-print">
            <span class="text-xs font-bold text-emerald-400">✅ الخطاطة جاهزة (قابل للتعديل باللمس)</span>
            <button type="button" onclick="window.print()" class="px-5 py-2 rounded-xl bg-emerald-600 text-xs font-black text-white shadow-lg">🖨️ طباعة / PDF</button>
        </div>

        <div id="sheetWrapper" class="hidden sheet-scroll-viewport">
            <div id="ncmSheet" class="ncm-sheet" dir="rtl">
                <div class="ncm-top-banner">
                    <div class="flex-1">
                        <div id="hdrTitle" contenteditable="true" class="text-base font-black text-white leading-snug mb-1"></div>
                        <div id="hdrSub" contenteditable="true" class="text-xs font-bold text-amber-200"></div>
                    </div>
                    <div class="ncm-orange-badge">
                        <div id="hdrBadgeLabel" class="text-[10px] font-bold uppercase opacity-95">خطاطة رقم</div>
                        <div id="hdrBadgeNum" contenteditable="true" class="text-2xl font-black leading-none mt-0.5">10</div>
                    </div>
                </div>

                <div class="ncm-objectives-box">
                    <span id="objLabel" class="font-black text-slate-900">أهداف التعلم: </span>
                    <span id="objText" contenteditable="true" class="text-slate-700 font-semibold"></span>
                </div>

                <div id="mindmapContainer" class="mindmap-container">
                    <svg id="pathSvg"></svg>
                    <div class="ncm-grid-layout">
                        <div id="colFirst" class="flex flex-col justify-center gap-4"></div>
                        <div id="colCenter" class="flex flex-col items-center justify-center gap-4"></div>
                        <div id="colLast" class="flex flex-col justify-center gap-4"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== القسم 2: حل المسائل ==================== -->
    <div id="sec-solver" class="app-section hidden max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <h2 class="text-base md:text-lg font-black text-cyan-400 mb-1">🧮 حلّال المسائل والتمارين (بنفس لغة التمرين)</h2>
            <p class="text-xs text-slate-400 mb-4">ارفع صورة التمرين أو ملفاً للحصول على الحل المفصل خطوة بخطوة.</p>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div class="md:col-span-2">
                    <div class="flex gap-2 mb-3">
                        <label class="flex-1 cursor-pointer bg-slate-800 hover:bg-slate-700 border-2 border-dashed border-cyan-500/40 rounded-2xl p-3 text-center flex items-center justify-center gap-2">
                            <span>📷</span>
                            <span id="solverFileName" class="text-xs font-bold text-slate-200">ارفع صورة المسألة أو ملف</span>
                            <input type="file" id="solverFileInput" accept="image/*,.pdf,.pptx,.txt" class="hidden" onchange="handleToolFile(this, 'solver')">
                        </label>
                        <button type="button" id="solverClearBtn" onclick="clearToolFile('solver')" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="solverInput" rows="4" placeholder="أو اكتب نص المسألة هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs"></textarea>
                </div>
                <div class="bg-slate-900/70 p-4 rounded-2xl border border-slate-800 flex flex-col justify-between">
                    <div>
                        <label class="block text-xs font-bold text-cyan-400 mb-1.5">التخصص:</label>
                        <select id="solverDomain" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-2.5">
                            <option value="math">📐 الرياضيات</option>
                            <option value="physics">⚡ الفيزياء والكيمياء</option>
                            <option value="science">🧬 العلوم</option>
                            <option value="languages">📖 اللغات والقواعد</option>
                        </select>
                        <label class="block text-xs font-bold text-cyan-400 mb-1.5">لغة الإجابة:</label>
                        <select id="solverLang" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                            <option value="auto">تلقائي (نفس لغة التمرين المرفوع)</option>
                            <option value="fr">Français (100%)</option>
                            <option value="ar">العربية (100%)</option>
                            <option value="en">English (100%)</option>
                        </select>
                    </div>
                </div>
            </div>
            <button type="button" onclick="runSmartTool('solver')" id="solverBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-cyan-600 to-blue-600 font-black text-white text-sm shadow-lg">حل المسألة بدقة متناهية 🚀</button>
        </div>
        <div id="solverResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-bold text-emerald-400">✅ الحل العلمي المفصل</span>
                <div class="flex gap-2">
                    <button type="button" onclick="copyText('solverOutput')" class="px-3 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button type="button" onclick="window.print()" class="px-3 py-1.5 rounded-xl bg-blue-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
                </div>
            </div>
            <div id="solverOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 3: الملخص الذكي ==================== -->
    <div id="sec-summarizer" class="app-section hidden max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <h2 class="text-base md:text-lg font-black text-amber-400 mb-1">📑 الملخص الذكي للملفات والدروس</h2>
            <p class="text-xs text-slate-400 mb-4">ارفع أي ملف لتحويله إلى ملخص احترافي مهيكل.</p>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div class="md:col-span-2">
                    <div class="flex gap-2 mb-3">
                        <label class="flex-1 cursor-pointer bg-slate-800 hover:bg-slate-700 border-2 border-dashed border-amber-500/40 rounded-2xl p-3 text-center flex items-center justify-center gap-2">
                            <span>📄</span>
                            <span id="summarizerFileName" class="text-xs font-bold text-slate-200">ارفع ملفاً أو صورة للتلخيص</span>
                            <input type="file" id="summarizerFileInput" accept=".pdf,.pptx,image/*,.txt" class="hidden" onchange="handleToolFile(this, 'summarizer')">
                        </label>
                        <button type="button" id="summarizerClearBtn" onclick="clearToolFile('summarizer')" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="summarizerInput" rows="4" placeholder="أو الصق النص هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs"></textarea>
                </div>
                <div class="bg-slate-900/70 p-4 rounded-2xl border border-slate-800">
                    <label class="block text-xs font-bold text-amber-400 mb-2">لغة الملخص:</label>
                    <select id="summarizerLang" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="auto">تلقائي (نفس لغة الملف الأصلي)</option>
                        <option value="fr">Français (100%)</option>
                        <option value="ar">العربية (100%)</option>
                        <option value="en">English (100%)</option>
                    </select>
                </div>
            </div>
            <button type="button" onclick="runSmartTool('summarizer')" id="summarizerBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-amber-500 to-orange-600 font-black text-slate-950 text-sm shadow-lg">توليد الملخص الاحترافي الآن ✨</button>
        </div>
        <div id="summarizerResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-bold text-amber-400">✅ الملخص المهيكل</span>
                <button type="button" onclick="window.print()" class="px-3 py-1.5 rounded-xl bg-amber-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
            </div>
            <div id="summarizerOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 4: الترجمة ==================== -->
    <div id="sec-translator" class="app-section hidden max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <h2 class="text-base md:text-lg font-black text-emerald-400 mb-1">🌐 المترجم الأكاديمي والتربوي الدقيق</h2>
            <p class="text-xs text-slate-400 mb-4">ترجمة دقيقة تحافظ على المصطلحات والمعادلات.</p>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div class="md:col-span-2">
                    <div class="flex gap-2 mb-3">
                        <label class="flex-1 cursor-pointer bg-slate-800 hover:bg-slate-700 border-2 border-dashed border-emerald-500/40 rounded-2xl p-3 text-center flex items-center justify-center gap-2">
                            <span>🌍</span>
                            <span id="translatorFileName" class="text-xs font-bold text-slate-200">ارفع ملفاً أو صورة للترجمة</span>
                            <input type="file" id="translatorFileInput" accept=".pdf,.pptx,image/*,.txt" class="hidden" onchange="handleToolFile(this, 'translator')">
                        </label>
                        <button type="button" id="translatorClearBtn" onclick="clearToolFile('translator')" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="translatorInput" rows="4" placeholder="أو اكتب النص للترجمة..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs"></textarea>
                </div>
                <div class="bg-slate-900/70 p-4 rounded-2xl border border-slate-800">
                    <label class="block text-xs font-bold text-emerald-400 mb-2">الترجمة إلى:</label>
                    <select id="translatorTarget" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="French (Français académique)">الفرنسية (Français)</option>
                        <option value="Modern Standard Arabic (العربية الفصحى)">العربية</option>
                        <option value="Academic English">الإنجليزية (English)</option>
                    </select>
                </div>
            </div>
            <button type="button" onclick="runSmartTool('translator')" id="translatorBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-emerald-600 to-teal-600 font-black text-white text-sm shadow-lg">ترجمة فورية دقيقة 🌐</button>
        </div>
        <div id="translatorResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-bold text-emerald-400">✅ النص المترجم</span>
                <button type="button" onclick="window.print()" class="px-3 py-1.5 rounded-xl bg-emerald-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
            </div>
            <div id="translatorOutput" class="prose-output"></div>
        </div>
    </div>

    <script>
        let stationsCount = 4;
        let ncmBase64 = null, ncmMime = null, ncmUploadedFilename = '';
        let toolFiles = { solver: {}, summarizer: {}, translator: {} };

        document.getElementById('apiKeyInput').value = localStorage.getItem('gemini_api_key') || '';

        function renderFormattedOutput(elementId, rawMarkdown) {
            const el = document.getElementById(elementId);
            if (!el) return;
            const mathBlocks = [];
            let protectedText = (rawMarkdown || '')
                .replace(/\$\$[\s\S]*?\$\$/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; })
                .replace(/\\\[[\s\S]*?\\\]/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; })
                .replace(/\\\([\s\S]*?\\\)/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; })
                .replace(/\$([^\$\n]+?)\$/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; });

            let html = marked.parse(protectedText);
            html = html.replace(/@@MATH_BLOCK_(\d+)@@/g, (_, idx) => mathBlocks[parseInt(idx, 10)]);

            const textWithoutMath = rawMarkdown.replace(/\$\$[\s\S]*?\$\$|\$[^\$\n]+?\$/g, '');
            const arabicChars = (textWithoutMath.match(/[\u0600-\u06FF]/g) || []).length;
            const latinChars = (textWithoutMath.match(/[a-zA-ZéèêëàâîïôùûçÉÈÊËÀÂÎÏÔÙÛÇ]/g) || []).length;
            const isRtl = arabicChars > latinChars;

            el.setAttribute('dir', isRtl ? 'rtl' : 'ltr');
            el.innerHTML = html;
            if (window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise([el]).catch(() => {});
            }
        }

        function switchSection(secId, btn) {
            document.querySelectorAll('.app-section').forEach(el => el.classList.add('hidden'));
            document.getElementById('sec-' + secId).classList.remove('hidden');
            document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            if (secId === 'ncm') setTimeout(drawConnectors, 60);
        }

        function toggleApiModal() { document.getElementById('apiModal').classList.toggle('hidden'); }
        function saveApiKey() {
            localStorage.setItem('gemini_api_key', document.getElementById('apiKeyInput').value.trim());
            toggleApiModal();
            alert('تم الحفظ!');
        }
        function setStations(num, btn) {
            stationsCount = parseInt(num, 10);
            document.querySelectorAll('.st-btn').forEach(b => {
                b.className = "st-btn py-1.5 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs";
            });
            btn.className = "st-btn py-1.5 rounded-xl border border-cyan-500 bg-cyan-500/20 text-cyan-300 font-black text-xs";
        }

        function compressImageFile(file, callback) {
            const reader = new FileReader();
            reader.onload = e => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    const maxDim = 1400;
                    let w = img.width, h = img.height;
                    if (w > maxDim || h > maxDim) {
                        if (w > h) { h = Math.round(h * maxDim / w); w = maxDim; }
                        else { w = Math.round(w * maxDim / h); h = maxDim; }
                    }
                    canvas.width = w; canvas.height = h;
                    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                    callback(canvas.toDataURL('image/jpeg', 0.84).split(',')[1], 'image/jpeg');
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        }

        async function handleNcmFile(input) {
            const file = input.files[0];
            if (!file) return;
            ncmUploadedFilename = file.name;
            document.getElementById('ncmFileName').innerText = "⏳ جاري التحليل: " + file.name;
            document.getElementById('ncmClearBtn').classList.remove('hidden');
            if (file.name.toLowerCase().endsWith('.pptx')) {
                const fd = new FormData(); fd.append('file', file);
                const res = await fetch('/extract_pptx', { method: 'POST', body: fd });
                const data = await res.json();
                if (data.text) { document.getElementById('ncmTextInput').value = data.text; ncmBase64 = null; }
                return;
            }
            if (file.type === 'application/pdf') {
                const reader = new FileReader();
                reader.onload = e => { ncmBase64 = e.target.result.split(',')[1]; ncmMime = 'application/pdf'; };
                reader.readAsDataURL(file);
            } else if (file.type.startsWith('image/')) {
                compressImageFile(file, (b, m) => { ncmBase64 = b; ncmMime = m; });
            } else {
                const reader = new FileReader();
                reader.onload = e => { document.getElementById('ncmTextInput').value = e.target.result; ncmBase64 = null; };
                reader.readAsText(file);
            }
        }
        function clearNcmFile() {
            document.getElementById('ncmFileInput').value = '';
            document.getElementById('ncmFileName').innerText = 'اختر ملف (.pptx / .pdf / صورة)';
            document.getElementById('ncmClearBtn').classList.add('hidden');
            ncmBase64 = null; ncmMime = null;
        }

        async function handleToolFile(input, toolKey) {
            const file = input.files[0];
            if (!file) return;
            document.getElementById(toolKey + 'FileName').innerText = "⏳ جاري القراءة: " + file.name;
            document.getElementById(toolKey + 'ClearBtn').classList.remove('hidden');
            if (file.name.toLowerCase().endsWith('.pptx')) {
                const fd = new FormData(); fd.append('file', file);
                const res = await fetch('/extract_pptx', { method: 'POST', body: fd });
                const data = await res.json();
                if (data.text) document.getElementById(toolKey + 'Input').value = data.text;
            } else if (file.type === 'application/pdf') {
                const reader = new FileReader();
                reader.onload = e => { toolFiles[toolKey] = { b64: e.target.result.split(',')[1], mime: 'application/pdf' }; };
                reader.readAsDataURL(file);
            } else if (file.type.startsWith('image/')) {
                compressImageFile(file, (b, m) => { toolFiles[toolKey] = { b64: b, mime: m }; });
            } else {
                const reader = new FileReader();
                reader.onload = e => { document.getElementById(toolKey + 'Input').value = e.target.result; };
                reader.readAsText(file);
            }
        }
        function clearToolFile(toolKey) {
            document.getElementById(toolKey + 'FileInput').value = '';
            toolFiles[toolKey] = {};
            document.getElementById(toolKey + 'FileName').innerText = 'ارفع ملفاً أو صورة';
            document.getElementById(toolKey + 'ClearBtn').classList.add('hidden');
        }

        async function generateNCM() {
            const text = document.getElementById('ncmTextInput').value.trim();
            const ncmNum = document.getElementById('ncmNumInput').value.trim() || '10';
            const apiKey = localStorage.getItem('gemini_api_key');
            if (!text && !ncmBase64) return alert('يرجى رفع ملف الدرس أو لصق محتواه.');
            const btn = document.getElementById('ncmGenBtn');
            btn.disabled = true; btn.innerText = '⏳ جاري التوليد...';
            try {
                const res = await fetch('/generate_ncm', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ text, filename: ncmUploadedFilename, stations: stationsCount, ncm_num: ncmNum, meta_overrides: { level: document.getElementById('metaLevel').value.trim(), periode: document.getElementById('metaPeriode').value.trim(), unite: document.getElementById('metaUnite').value.trim(), semaine: document.getElementById('metaSemaine').value.trim(), seance: document.getElementById('metaSeance').value.trim() }, file_b64: ncmBase64, mime_type: ncmMime, api_key: apiKey })
                });
                const data = await res.json();
                if (data.error) { alert(data.error); if (data.need_key) toggleApiModal(); }
                else { renderNCMSheet(data.result, ncmNum); }
            } catch(e) { alert('خطأ في الاتصال.'); }
            finally { btn.disabled = false; btn.innerText = 'توليد الخطاطة الرسمية بالترويسة الكاملة ⚡'; }
        }

        const stationColors = ['#2563eb', '#dc2626', '#d97706', '#16a34a', '#7c3aed', '#0d9488'];

        function createStationCard(st, idx) {
            const color = stationColors[idx % stationColors.length];
            const cleanTitle = (st.title || '').replace(/^\d+[\.\-\s]*/, '');
            const bulletsHtml = (st.bullets || []).map(b => `
                <li class="mb-1.5 flex items-start gap-2">
                    <span style="color: ${color};" class="font-black mt-0.5">•</span>
                    <div contenteditable="true">
                        ${b.label ? `<strong class="text-slate-900 font-extrabold">${b.label} : </strong>` : ''}
                        <span class="text-slate-700 font-medium">${b.text || ''}</span>
                    </div>
                </li>
            `).join('');
            return `<div class="station-box" style="border-top: 4px solid ${color};"><div class="station-header-bar" style="background: ${color};"><span contenteditable="true">${idx + 1}. ${cleanTitle}</span>${st.duration ? `<span contenteditable="true" class="station-time-tag">${st.duration}</span>` : ''}</div><div class="station-content-body"><ul class="list-none p-0 m-0">${bulletsHtml}</ul></div></div>`;
        }

        function createCenterHub(d, isFr, ncmNum) {
            const tag1 = isFr ? "Enseignement Explicite" : "التعليم الصريح";
            const tag2 = isFr ? "École Pionnière" : "المدرسة الرائدة";
            const seanceBadge = d.seance_ncm_badge || (isFr ? `NCM ${d.ncm_number || ncmNum}` : `خطاطة رقم (${d.ncm_number || ncmNum})`);
            return `<div class="center-hub-box"><div id="centralHub" class="center-blue-circle"><div class="text-[11px] font-extrabold text-amber-300 tracking-wide mb-0.5">${tag1}</div><div class="text-[11px] font-bold text-white mb-1.5 opacity-95">${tag2}</div><div contenteditable="true" class="text-sm md:text-base font-black text-white bg-white/20 py-1 px-4 rounded-full mb-1.5 border border-white/30 shadow-inner">${d.subject_level || ''}</div><div contenteditable="true" class="text-[11px] font-bold text-slate-100 mb-1.5 leading-tight">${d.unit_week || ''}</div><div contenteditable="true" class="text-xs font-black text-amber-300 bg-amber-500/25 border border-amber-300/40 px-3 py-0.5 rounded-full mb-1">${seanceBadge}</div>${d.livret_pages ? `<div contenteditable="true" class="text-[10.5px] font-semibold text-cyan-200 bg-black/30 py-0.5 px-2.5 rounded-full">${d.livret_pages}</div>` : ''}</div></div>`;
        }

        function drawConnectors() {
            const container = document.getElementById('mindmapContainer');
            const svg = document.getElementById('pathSvg');
            const hub = document.getElementById('centralHub');
            if (!container || !svg || !hub) return;
            const cRect = container.getBoundingClientRect();
            if (cRect.width === 0) return;
            svg.setAttribute('viewBox', `0 0 ${cRect.width} ${cRect.height}`);
            svg.innerHTML = '';
            const hubRect = hub.getBoundingClientRect();
            const hx = hubRect.left - cRect.left + hubRect.width / 2;
            const hy = hubRect.top - cRect.top + hubRect.height / 2;
            const radius = hubRect.width / 2;

            container.querySelectorAll('.station-box').forEach((card, i) => {
                const color = stationColors[i % stationColors.length];
                const cardRect = card.getBoundingClientRect();
                const cx = cardRect.left - cRect.left + cardRect.width / 2;
                const cy = cardRect.top - cRect.top + cardRect.height / 2;
                let targetX = cx < hx - 80 ? cardRect.right - cRect.left : (cx > hx + 80 ? cardRect.left - cRect.left : cx);
                let targetY = cx < hx - 80 || cx > hx + 80 ? cy : (cy < hy ? cardRect.bottom - cRect.top : cardRect.top - cRect.top);
                const angle = Math.atan2(targetY - hy, targetX - hx);
                const startX = hx + Math.cos(angle) * (radius + 2);
                const startY = hy + Math.sin(angle) * (radius + 2);
                const midX = (startX + targetX) / 2;
                const dPath = Math.abs(cx - hx) > 80 ? `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${targetY}, ${targetX} ${targetY}` : `M ${startX} ${startY} L ${targetX} ${targetY}`;

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', dPath); path.setAttribute('stroke', color); path.setAttribute('stroke-width', '2.8'); path.setAttribute('stroke-dasharray', '6,5'); path.setAttribute('fill', 'none');
                svg.appendChild(path);
            });
        }

        function renderNCMSheet(d, ncmNum) {
            const isFr = (d.lang || '').toLowerCase() === 'fr';
            const sheet = document.getElementById('ncmSheet');
            sheet.setAttribute('dir', isFr ? 'ltr' : 'rtl');
            document.getElementById('hdrTitle').innerText = d.header_title || '';
            document.getElementById('hdrSub').innerText = d.lesson_subtitle || '';
            document.getElementById('hdrBadgeLabel').innerText = isFr ? 'NCM' : 'خطاطة رقم';
            document.getElementById('hdrBadgeNum').innerText = d.ncm_number || ncmNum;
            document.getElementById('objLabel').innerText = isFr ? "Objectifs d'apprentissage : " : "أهداف التعلم: ";
            document.getElementById('objText').innerText = d.objectives || '';

            const stations = (d.stations || []).slice(0, stationsCount);
            const colFirst = document.getElementById('colFirst');
            const colCenter = document.getElementById('colCenter');
            const colLast = document.getElementById('colLast');
            colFirst.innerHTML = ''; colCenter.innerHTML = ''; colLast.innerHTML = '';
            const hubHtml = createCenterHub(d, isFr, d.ncm_number || ncmNum);

            if (stations.length === 2) {
                colFirst.innerHTML = createStationCard(stations[0], 0); colCenter.innerHTML = hubHtml; colLast.innerHTML = createStationCard(stations[1], 1);
            } else if (stations.length === 3) {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1); colCenter.innerHTML = hubHtml; colLast.innerHTML = createStationCard(stations[2], 2);
            } else if (stations.length === 4) {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1); colCenter.innerHTML = hubHtml; colLast.innerHTML = createStationCard(stations[2], 2) + createStationCard(stations[3], 3);
            } else if (stations.length === 5) {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1); colCenter.innerHTML = hubHtml + createStationCard(stations[2], 2); colLast.innerHTML = createStationCard(stations[3], 3) + createStationCard(stations[4], 4);
            } else {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1); colCenter.innerHTML = createStationCard(stations[2], 2) + hubHtml + createStationCard(stations[3], 3); colLast.innerHTML = createStationCard(stations[4], 4) + createStationCard(stations[5], 5);
            }

            document.getElementById('printBar').classList.remove('hidden');
            document.getElementById('sheetWrapper').classList.remove('hidden');
            setTimeout(() => { drawConnectors(); document.getElementById('sheetWrapper').scrollIntoView({ behavior: 'smooth' }); }, 120);
        }

        async function runSmartTool(toolType) {
            const text = document.getElementById(toolType + 'Input').value.trim();
            const fileObj = toolFiles[toolType] || {};
            const apiKey = localStorage.getItem('gemini_api_key');
            if (!text && !fileObj.b64) return alert('يرجى إدخال النص أو رفع ملف أولاً.');
            const btn = document.getElementById(toolType + 'Btn');
            btn.disabled = true; btn.innerText = '⏳ جاري المعالجة...';

            let extraOptions = {};
            if (toolType === 'solver') {
                extraOptions = { domain: document.getElementById('solverDomain').value, lang: document.getElementById('solverLang').value, detail: 'detailed' };
            } else if (toolType === 'summarizer') {
                extraOptions = { style: 'structured', lang: document.getElementById('summarizerLang').value };
            } else if (toolType === 'translator') {
                extraOptions = { target: document.getElementById('translatorTarget').value, tone: 'Academic' };
            }

            try {
                const res = await fetch('/smart_tool', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ tool: toolType, text, options: extraOptions, file_b64: fileObj.b64, mime_type: fileObj.mime, api_key: apiKey })
                });
                const data = await res.json();
                if (data.error) { alert(data.error); if (data.need_key) toggleApiModal(); }
                else {
                    document.getElementById(toolType + 'ResultBox').classList.remove('hidden');
                    renderFormattedOutput(toolType + 'Output', data.result);
                    document.getElementById(toolType + 'ResultBox').scrollIntoView({ behavior: 'smooth' });
                }
            } catch(e) { alert('خطأ في الاتصال.'); }
            finally { btn.disabled = false; btn.innerText = 'تنفيذ العملية 🚀'; }
        }

        function copyText(elId) {
            navigator.clipboard.writeText(document.getElementById(elId).innerText);
            alert('تم النسخ!');
        }
        window.addEventListener('resize', drawConnectors);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/extract_pptx', methods=['POST'])
def handle_pptx():
    if 'file' not in request.files: return jsonify({'error': 'لم يتم إرفاق ملف'})
    return jsonify({'text': extract_pptx_text(request.files['file'].stream)})

@app.route('/generate_ncm', methods=['POST'])
def generate_ncm():
    data = request.get_json(force=True)
    text = data.get('text', '')
    filename = data.get('filename', '')
    stations = int(data.get('stations', 4))
    ncm_num = data.get('ncm_num', '10')
    overrides = data.get('meta_overrides') or {}
    file_b64 = data.get('file_b64')
    mime_type = data.get('mime_type')
    api_key = (data.get('api_key') or os.environ.get('GEMINI_API_KEY') or '').strip()

    if not api_key: return jsonify({'error': 'يرجى إدخال مفتاح API من (⚙️).', 'need_key': True})

    fn_meta = parse_filename_metadata(filename)
    lvl = overrides.get('level') or fn_meta.get('level') or ''
    per = overrides.get('periode') or fn_meta.get('periode') or ''
    uni = overrides.get('unite') or fn_meta.get('unite') or ''
    sem = overrides.get('semaine') or fn_meta.get('semaine') or ''
    sea = overrides.get('seance') or fn_meta.get('seance') or ''

    is_fr = filename.upper().startswith('FR') or (text and len(re.findall(r'[a-zA-Zéèêëàâîïôùûç]', text[:2000])) > len(re.findall(r'[\u0600-\u06FF]', text[:2000])))

    if is_fr:
        system_prompt = f"""Tu es un expert pédagogique de l'Enseignement Explicite (École Pionnière au Maroc).
RÈGLE DE LANGUE : Réponds 100% en FRANÇAIS ("lang": "fr"). Zéro mot en arabe !
Format header_title : "Français – Niveau {lvl or 'X'} | Période {per or 'P'} - Unité {uni or 'U'} - Semaine {sem or 'W'} - Séance {sea or 'S'}"
Format lesson_subtitle : "Enseignement explicite | [Titre de la leçon] (Livret : p. ...)"
Divise en EXACTEMENT ({stations}) stations avec des durées réelles (ex: 15 min).
Retourne UNIQUEMENT un JSON :
{{"lang":"fr","ncm_number":"{ncm_num}","header_title":"...","lesson_subtitle":"...","objectives":"...","subject_level":"Français N{lvl or '2'}","unit_week":"Période {per or '2'} - Unité {uni or '1'} | Semaine {sem or '2'}","seance_ncm_badge":"Séance {sea or '4'} (NCM {ncm_num})","livret_pages":"Livret : p. ...","stations":[{{"title":"...","duration":"15 min","bullets":[{{"label":"...","text":"..."}}]}}]}}"""
    else:
        system_prompt = f"""أنت خبير بيداغوجي في برنامج التعليم الصريح بالمدرسة الرائدة.
قاعدة اللغة: رد باللغة العربية 100% ("lang": "ar").
header_title: "[المادة] – المستوى {lvl or '2'} | المرحلة {per or '2'} - الوحدة {uni or '1'} - الأسبوع {sem or '2'} - الحصة {sea or '4'}"
lesson_subtitle: "برنامج التعليم الصريح | [عنوان الدرس] (الكراسة: ص. ...)"
قسّم إلى ({stations}) محطات بدقة مع مدد زمنية حقيقية (مثال: 15 د).
أرجع JSON صالحاً فقط:
{{"lang":"ar","ncm_number":"{ncm_num}","header_title":"...","lesson_subtitle":"...","objectives":"...","subject_level":"اللغة العربية {lvl or '2'}","unit_week":"المرحلة {per or '2'} – الوحدة {uni or '1'} | الأسبوع {sem or '2'}","seance_ncm_badge":"الحصة {sea or '4'} (خطاطة {ncm_num})","livret_pages":"الكراسة: ص. ...","stations":[{{"title":"...","duration":"15 د","bullets":[{{"label":"...","text":"..."}}]}}]}}"""

    parts = [{"text": system_prompt + "\n\nContent:\n" + (text[:35000] if text else "Analyze attached file.")}]
    if file_b64 and mime_type: parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    raw_text, err = call_gemini_api(api_key, parts, json_mode=True, temperature=0.1)
    if err or not raw_text: return jsonify({'error': f'تعذر التوليد: {err}'})
    try:
        res_json = json.loads(re.search(r'\{[\s\S]*\}', raw_text).group(0))
        if 'stations' in res_json: res_json['stations'] = res_json['stations'][:stations]
        return jsonify({'result': res_json})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/smart_tool', methods=['POST'])
def smart_tool():
    data = request.get_json(force=True)
    tool = data.get('tool'); text = data.get('text', ''); options = data.get('options') or {}
    file_b64 = data.get('file_b64'); mime_type = data.get('mime_type')
    api_key = (data.get('api_key') or os.environ.get('GEMINI_API_KEY') or '').strip()
    if not api_key: return jsonify({'error': 'أدخل مفتاح API.', 'need_key': True})

    lang_opt = options.get('lang', 'auto')
    if lang_opt == 'fr': lang_rule = "MANDATORY: Answer 100% in FRENCH. ZERO Arabic words."
    elif lang_opt == 'ar': lang_rule = "MANDATORY: Answer 100% in ARABIC."
    elif lang_opt == 'en': lang_rule = "MANDATORY: Answer 100% in ENGLISH."
    else: lang_rule = "Mirror the exact language of the input document/file (French input -> French output, Arabic input -> Arabic output)."

    prompt = f"You are an expert AI academic assistant. {lang_rule}\nSolve/Process the input thoroughly with professional formatting and LaTeX math ($...$ or $$...$$)."
    parts = [{"text": prompt + "\n\nInput:\n" + (text[:35000] if text else "Process the attached file.")}]
    if file_b64 and mime_type: parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    raw_text, err = call_gemini_api(api_key, parts, json_mode=False, temperature=0.15)
    if err or not raw_text: return jsonify({'error': f'خطأ: {err}'})
    return jsonify({'result': raw_text})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
