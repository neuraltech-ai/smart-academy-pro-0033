from flask import Flask, render_template_string, request, jsonify
import requests
import os
import json
import re
import time
import zipfile
import threading
import xml.etree.ElementTree as ET

app = Flask(__name__)
AVAILABLE_MODELS_CACHE = {}

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "alive": True}), 200

def keep_alive_ping():
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://smart-academy-pro.onrender.com") + "/health"
    while True:
        time.sleep(600)
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass

threading.Thread(target=keep_alive_ping, daemon=True).start()

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
    return ["gemini-2.0-flash", "gemini-3.8-flash", "gemini-pro"]

def extract_pptx_text(file_stream):
    text_runs = []
    try:
        with zipfile.ZipFile(file_stream) as z:
            slide_files = [f for f in z.namelist() if f.startswith('ppt/slides/slide') and f.endswith('.xml')]
            slide_files.sort(key=lambda x: int(re.search(r'slide(\d+)\.xml', x).group(1)) if re.search(r'slide(\d+)\.xml', x) else 0)
            for idx, slide in enumerate(slide_files, 1):
                tree = ET.fromstring(z.read(slide))
                slide_texts = [elem.text.strip() for elem in tree.iter() if elem.tag.endswith('}t') and elem.text and elem.text.strip()]
                if slide_texts:
                    text_runs.append(f"[Slide {idx}]: " + " | ".join(slide_texts))
    except Exception as e:
        return f"Error: {str(e)}"
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
    payload = {"contents": [{"parts": parts}], "generationConfig": gen_config}
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': api_key}
    last_error = ""
    for attempt in range(2):
        for model_name in candidate_models:
            try:
                res = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
                    json=payload,
                    headers=headers,
                    timeout=75
                )
                res_data = res.json()
                if res.status_code == 200 and 'candidates' in res_data:
                    return res_data['candidates'][0]['content']['parts'][0]['text'], None
                else:
                    last_error = res_data.get('error', {}).get('message', 'خطأ في الاستجابة')
                    time.sleep(0.5)
            except Exception as e:
                last_error = str(e)
    return None, last_error

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>الأكاديمية الذكية Pro | المنصة التربوية والعلمية</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
        window.MathJax = {
            tex: { inlineMath: [['$', '$'], ['\\(', '\\)']], displayMath: [['$$', '$$'], ['\\[', '\\]']], processEscapes: true },
            options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre'] }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Cairo', sans-serif;
            background: radial-gradient(circle at 50% 0%, #172554 0%, #090d16 65%);
            color: #f8fafc;
            margin: 0;
            min-height: 100vh;
            overflow-x: hidden;
        }
        .glass-panel {
            background: rgba(15, 23, 42, 0.88);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(148, 163, 184, 0.14);
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
        }
        .app-section { display: none; animation: fadeIn 0.22s ease-out; }
        .app-section.active-section { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

        .nav-card, .st-btn {
            cursor: pointer;
            user-select: none;
            -webkit-tap-highlight-color: transparent;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .nav-card.active {
            border-color: #38bdf8 !important;
            background: linear-gradient(145deg, rgba(14, 165, 233, 0.22), rgba(30, 58, 138, 0.35)) !important;
            box-shadow: 0 8px 25px -4px rgba(56, 189, 248, 0.35);
            transform: translateY(-2px);
        }
        .st-btn.active-st {
            border-color: #06b6d4 !important;
            background: rgba(6, 182, 212, 0.25) !important;
            color: #67e8f9 !important;
            box-shadow: 0 0 12px rgba(6, 182, 212, 0.3);
        }
        .cta-btn {
            transition: all 0.2s ease;
            box-shadow: 0 10px 25px -5px rgba(6, 182, 212, 0.45);
        }
        .cta-btn:hover { filter: brightness(1.07); }
        .cta-btn:active { transform: scale(0.985); }

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

        /* تنسيق احترافي عالي الدقة للمخرجات العلمية والأكاديمية */
        .prose-output { line-height: 1.95; font-size: 15px; color: #e2e8f0; }
        .prose-output h1, .prose-output h2, .prose-output h3 {
            color: #38bdf8;
            font-weight: 900;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
            padding-bottom: 0.35rem;
            border-bottom: 1px solid rgba(56, 189, 248, 0.2);
        }
        .prose-output p { margin-bottom: 0.9rem; }
        .prose-output ul { list-style-type: disc; padding-inline-start: 1.5rem; margin-bottom: 1rem; }
        .prose-output ol { list-style-type: decimal; padding-inline-start: 1.5rem; margin-bottom: 1rem; }
        .prose-output li { margin-bottom: 0.45rem; }
        .prose-output blockquote {
            background: rgba(14, 165, 233, 0.1);
            border-inline-start: 4px solid #38bdf8;
            padding: 12px 16px;
            border-radius: 10px;
            margin: 1.1rem 0;
            color: #f8fafc;
        }
        .prose-output table { width: 100%; border-collapse: collapse; margin: 1.2rem 0; border-radius: 10px; overflow: hidden; }
        .prose-output th, .prose-output td { border: 1px solid #334155; padding: 10px 14px; }
        .prose-output th { background: #1e293b; color: #38bdf8; font-weight: 800; }
        .prose-output strong { color: #fde047; font-weight: 800; }
        mjx-container { overflow-x: auto; overflow-y: hidden; max-width: 100%; padding: 4px 2px; }
        mjx-container[display="true"] {
            background: rgba(15, 23, 42, 0.75);
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 12px;
            padding: 12px 16px;
            margin: 12px 0 !important;
        }

        @media print {
            @page { size: A4 landscape; margin: 4mm; }
            body { background: white !important; color: black !important; }
            .no-print { display: none !important; }
            .sheet-scroll-viewport { overflow: visible !important; display: block !important; }
            .ncm-sheet { box-shadow: none !important; border: none !important; width: 100% !important; min-width: 100% !important; padding: 2mm 4mm !important; }
            .prose-print-box { background: white !important; color: black !important; border: none !important; box-shadow: none !important; padding: 0 !important; }
            .prose-output, .prose-output p, .prose-output li { color: #0f172a !important; }
            .prose-output h1, .prose-output h2, .prose-output h3 { color: #1e3a8a !important; border-bottom-color: #cbd5e1 !important; }
            .prose-output strong { color: #0f172a !important; text-decoration: underline; }
            mjx-container[display="true"] { background: #f8fafc !important; border-color: #cbd5e1 !important; }
        }
    </style>
</head>
<body class="p-3 md:p-6">
    <div class="max-w-6xl mx-auto no-print mb-6">
        <!-- ترويسة احترافية نظيفة (مع نقر سري 5 مرات على الشعار لإدارة المفتاح عند الحاجة) -->
        <header class="glass-panel p-4 rounded-3xl flex items-center justify-between gap-4">
            <div class="flex items-center gap-3.5">
                <div onclick="secretAdminTap()" class="w-12 h-12 rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg cursor-pointer select-none">
                    <span class="text-2xl">🎓</span>
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="text-base md:text-lg font-black text-white tracking-wide">الأكاديمية الذكية <span class="text-cyan-400">Pro</span></h1>
                        <span class="hidden sm:inline-block px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">الإصدار المتقدم</span>
                    </div>
                    <p class="text-[11px] text-slate-400">بيئة الذكاء الاصطناعي للتخطيط التربوي والتحليل العلمي</p>
                </div>
            </div>
            <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/25">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span class="text-[11px] font-bold text-emerald-300">نشط 24/7</span>
            </div>
        </header>

        <!-- بطاقات التنقل الأربعة بدون رمز NCM وبمسميات عالمية -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3.5">
            <button type="button" onclick="switchSection('ncm')" id="card-ncm" class="nav-card active p-3.5 rounded-2xl bg-slate-900/90 border border-cyan-500/50 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">🗺️</span>
                <span class="text-xs font-black text-white">خطاطات المدرسة الرائدة</span>
                <span class="text-[10px] text-slate-400 font-semibold">هيكلة الدروس • التعليم الصريح</span>
            </button>
            <button type="button" onclick="switchSection('solver')" id="card-solver" class="nav-card p-3.5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">🔬</span>
                <span class="text-xs font-black text-slate-100">المختبر العلمي للمسائل</span>
                <span class="text-[10px] text-slate-400 font-semibold">برهنة معمّقة • خطوة بخطوة</span>
            </button>
            <button type="button" onclick="switchSection('summarizer')" id="card-summarizer" class="nav-card p-3.5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">📑</span>
                <span class="text-xs font-black text-slate-100">الملخص الأكاديمي الذكي</span>
                <span class="text-[10px] text-slate-400 font-semibold">استخلاص محاور ومفاهيم</span>
            </button>
            <button type="button" onclick="switchSection('translator')" id="card-translator" class="nav-card p-3.5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">🌐</span>
                <span class="text-xs font-black text-slate-100">المترجم الأكاديمي الدقيق</span>
                <span class="text-[10px] text-slate-400 font-semibold">ترجمة علمية وتربوية</span>
            </button>
        </div>

        <!-- نافذة إعداد المفتاح (مخفية ولا تظهر إلا بـ 5 نقرات على الشعار أو عند غياب المفتاح) -->
        <div id="apiModal" class="hidden fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
            <div class="glass-panel p-6 rounded-3xl max-w-md w-full border border-blue-500/40">
                <h3 class="text-base font-bold mb-2 text-cyan-400">إعداد مفتاح الخدمة السحابية (خاص بالمشرف)</h3>
                <input type="password" id="apiKeyInput" placeholder="أدخل مفتاح Gemini API هنا..." class="w-full p-3 rounded-xl bg-slate-900 border border-slate-700 text-white mb-4 text-left font-mono text-sm" dir="ltr">
                <div class="flex justify-end gap-2">
                    <button type="button" onclick="toggleApiModal()" class="px-4 py-2 rounded-xl bg-slate-800 text-xs font-bold">إغلاق</button>
                    <button type="button" onclick="saveApiKey()" class="px-5 py-2 rounded-xl bg-blue-600 text-white font-black text-xs">حفظ وتفعيل</button>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== القسم 1: خطاطات المدرسة الرائدة ==================== -->
    <div id="sec-ncm" class="app-section active-section max-w-6xl mx-auto">
        <div class="glass-panel rounded-3xl p-5 shadow-2xl mb-6 no-print">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-5">
                <div class="lg:col-span-2">
                    <label class="block text-xs font-bold text-cyan-400 mb-2">1. ارفع ملف الدرس أو الصق محتواه:</label>
                    <div class="flex items-center gap-2 mb-2.5">
                        <label class="flex-1 min-w-0 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-cyan-500/50 rounded-2xl p-3 text-center transition flex items-center justify-center gap-2">
                            <span class="text-lg flex-shrink-0">📂</span>
                            <span id="ncmFileName" class="text-xs font-bold text-slate-200 truncate">اختر ملف الدرس (.pptx / .pdf / صورة)</span>
                            <input type="file" id="ncmFileInput" accept=".pptx,.ppt,.pdf,image/*,.txt" class="hidden" onchange="handleNcmFile(this)">
                        </label>
                        <button type="button" id="ncmClearBtn" onclick="clearNcmFile()" class="hidden flex-shrink-0 px-3.5 py-3 rounded-2xl bg-red-500/20 border border-red-500/30 text-red-300 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="ncmTextInput" rows="3" placeholder="أو الصق نص الدرس أو الجذاذة هنا..." class="w-full p-3 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-cyan-500 outline-none"></textarea>
                </div>

                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-between">
                    <div>
                        <label class="block text-xs font-bold text-cyan-400 mb-2">2. عدد المحطات:</label>
                        <div class="grid grid-cols-5 gap-1.5 mb-3">
                            <button type="button" onclick="setStations(2)" id="st-btn-2" class="st-btn py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">2</button>
                            <button type="button" onclick="setStations(3)" id="st-btn-3" class="st-btn py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">3</button>
                            <button type="button" onclick="setStations(4)" id="st-btn-4" class="st-btn active-st py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">4</button>
                            <button type="button" onclick="setStations(5)" id="st-btn-5" class="st-btn py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">5</button>
                            <button type="button" onclick="setStations(6)" id="st-btn-6" class="st-btn py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">6</button>
                        </div>
                        <div class="grid grid-cols-3 gap-1.5 mb-2">
                            <input id="metaLevel" type="text" placeholder="المستوى" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaPeriode" type="text" placeholder="المرحلة" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaUnite" type="text" placeholder="الوحدة" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                        </div>
                        <div class="grid grid-cols-3 gap-1.5">
                            <input id="metaSemaine" type="text" placeholder="الأسبوع" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaSeance" type="text" placeholder="الحصة" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="ncmNumInput" type="text" value="10" placeholder="رقم الخطاطة" class="p-1.5 rounded-lg bg-slate-800 border border-amber-500/50 text-center font-black text-[11px] text-amber-300">
                        </div>
                    </div>
                </div>
            </div>

            <button type="button" onclick="generateNCM()" id="ncmGenBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 via-indigo-600 to-cyan-500 border border-cyan-300/30 font-black text-white text-sm tracking-wide flex items-center justify-center gap-2">
                <span>تصميم الخطاطة التربوية للدرس</span>
                <span class="text-base">⚡</span>
            </button>
        </div>

        <div id="printBar" class="hidden mb-3 flex flex-wrap items-center justify-between gap-2 glass-panel px-4 py-2.5 rounded-2xl no-print">
            <span class="text-xs font-bold text-emerald-400">✅ الخطاطة جاهزة (جميع النصوص قابلة للتعديل المباشر باللمس)</span>
            <button type="button" onclick="window.print()" class="px-5 py-2 rounded-xl bg-emerald-600 text-xs font-black text-white shadow-lg">🖨️ طباعة / حفظ PDF</button>
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

    <!-- ==================== القسم 2: المختبر التحليلي لحل المسائل ==================== -->
    <div id="sec-solver" class="app-section max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <div class="flex flex-wrap items-center justify-between gap-2 mb-4 pb-3 border-b border-slate-800">
                <div>
                    <h2 class="text-base md:text-lg font-black text-cyan-400 flex items-center gap-2">
                        <span>🔬</span>
                        <span>المختبر التحليلي لحل المسائل والتمارين العلمية</span>
                    </h2>
                    <p class="text-xs text-slate-400 mt-0.5">معالجة أكاديمية معمّقة، تأصيل للقواعد والمبرهنات، وبرهنة متدرجة خطوة بخطوة.</p>
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
                <div class="md:col-span-2">
                    <div class="flex items-center gap-2 mb-3">
                        <label class="flex-1 min-w-0 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-cyan-500/40 rounded-2xl p-3 text-center flex items-center justify-center gap-2">
                            <span class="text-lg flex-shrink-0">📷</span>
                            <span id="solverFileName" class="text-xs font-bold text-slate-200 truncate">ارفع صورة المسألة أو ملف التمرين (.pdf / .pptx / صورة)</span>
                            <input type="file" id="solverFileInput" accept="image/*,.pdf,.pptx,.txt" class="hidden" onchange="handleToolFile(this, 'solver')">
                        </label>
                        <button type="button" id="solverClearBtn" onclick="clearToolFile('solver')" class="hidden flex-shrink-0 px-3.5 py-3 rounded-2xl bg-red-500/20 border border-red-500/30 text-red-300 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="solverInput" rows="4" placeholder="أو اكتب نص المسألة أو المعادلات الرياضية هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-cyan-500 outline-none"></textarea>
                </div>

                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-between gap-2">
                    <div>
                        <label class="block text-[11px] font-bold text-cyan-400 mb-1">المجال العلمي:</label>
                        <select id="solverDomain" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-2.5">
                            <option value="Mathematics (Algebra, Analysis, Geometry, Probability)">📐 الرياضيات والهندسة</option>
                            <option value="Physics & Chemistry">⚡ الفيزياء والكيمياء</option>
                            <option value="Life & Earth Sciences (SVT) & Engineering">🧬 علوم الحياة والأرض والهندسة</option>
                            <option value="Languages, Grammar & Literature">📖 اللغات والقواعد والتحليل النصي</option>
                        </select>

                        <label class="block text-[11px] font-bold text-cyan-400 mb-1">منهجية ومستوى العمق:</label>
                        <select id="solverDepth" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-2.5">
                            <option value="deep">🎯 برهان معمّق ومفصل (مواصفات قياسية)</option>
                            <option value="pedagogical">💡 شرح بيداغوجي متدرج مع تبسيط المفاهيم</option>
                            <option value="concise">⚡ حل مركز ومباشر (الخطوات الأساسية)</option>
                        </select>

                        <label class="block text-[11px] font-bold text-cyan-400 mb-1">لغة التحرير:</label>
                        <select id="solverLang" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                            <option value="auto">تلقائي (مطابق للغة المسألة المرفوعة)</option>
                            <option value="fr">Français (تحرير أكاديمي فرنسي 100%)</option>
                            <option value="ar">العربية (تحرير علمي عربي 100%)</option>
                            <option value="en">English (Academic English 100%)</option>
                        </select>
                    </div>
                </div>
            </div>

            <button type="button" onclick="runSmartTool('solver')" id="solverBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-cyan-600 via-blue-600 to-indigo-600 border border-cyan-300/30 font-black text-white text-sm flex items-center justify-center gap-2">
                <span>بدء التحليل والبرهنة المعمّقة</span>
                <span>🚀</span>
            </button>
        </div>

        <div id="solverResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box mb-8">
            <div class="flex flex-wrap justify-between items-center border-b border-slate-700/80 pb-3 mb-4 no-print gap-2">
                <div class="flex items-center gap-2">
                    <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                    <span class="text-xs font-black text-emerald-400">التحليل الأكاديمي والحل المنهجي المفصل</span>
                </div>
                <div class="flex gap-2">
                    <button type="button" onclick="copyText('solverOutput')" class="px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-600 text-xs font-bold text-slate-200">📋 نسخ الحل</button>
                    <button type="button" onclick="window.print()" class="px-4 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-xs font-black text-white">🖨️ طباعة / PDF</button>
                </div>
            </div>
            <div id="solverOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 3: الملخص الأكاديمي الذكي ==================== -->
    <div id="sec-summarizer" class="app-section max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <div class="mb-4 pb-3 border-b border-slate-800">
                <h2 class="text-base md:text-lg font-black text-amber-400 flex items-center gap-2">
                    <span>📑</span>
                    <span>الملخص الأكاديمي وهيكلة المحاضرات والدروس</span>
                </h2>
                <p class="text-xs text-slate-400 mt-0.5">تحويل الملفات والمحاضرات الطويلة إلى ملخصات مركزة، جداول مقارنة، وقواعد أساسية.</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
                <div class="md:col-span-2">
                    <div class="flex items-center gap-2 mb-3">
                        <label class="flex-1 min-w-0 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-amber-500/40 rounded-2xl p-3 text-center flex items-center justify-center gap-2">
                            <span class="text-lg flex-shrink-0">📄</span>
                            <span id="summarizerFileName" class="text-xs font-bold text-slate-200 truncate">ارفع ملف الدرس أو المحاضرة (.pdf / .pptx / صورة)</span>
                            <input type="file" id="summarizerFileInput" accept=".pdf,.pptx,image/*,.txt" class="hidden" onchange="handleToolFile(this, 'summarizer')">
                        </label>
                        <button type="button" id="summarizerClearBtn" onclick="clearToolFile('summarizer')" class="hidden flex-shrink-0 px-3.5 py-3 rounded-2xl bg-red-500/20 border border-red-500/30 text-red-300 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="summarizerInput" rows="4" placeholder="أو الصق النص المراد تلخيصه وهيكلة محاوره هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-amber-500 outline-none"></textarea>
                </div>
                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-center">
                    <label class="block text-xs font-bold text-amber-400 mb-2">لغة الملخص المهيكل:</label>
                    <select id="summarizerLang" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="auto">تلقائي (مطابق للغة الملف الأصلي)</option>
                        <option value="fr">Français (100%)</option>
                        <option value="ar">العربية (100%)</option>
                        <option value="en">English (100%)</option>
                    </select>
                </div>
            </div>
            <button type="button" onclick="runSmartTool('summarizer')" id="summarizerBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-amber-500 to-orange-600 font-black text-slate-950 text-sm">استخلاص الملخص الأكاديمي المهيكل ✨</button>
        </div>
        <div id="summarizerResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box mb-8">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-black text-amber-400">✅ الملخص الأكاديمي المهيكل</span>
                <div class="flex gap-2">
                    <button type="button" onclick="copyText('summarizerOutput')" class="px-3.5 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button type="button" onclick="window.print()" class="px-4 py-1.5 rounded-xl bg-amber-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
                </div>
            </div>
            <div id="summarizerOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 4: المترجم الأكاديمي الدقيق ==================== -->
    <div id="sec-translator" class="app-section max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <div class="mb-4 pb-3 border-b border-slate-800">
                <h2 class="text-base md:text-lg font-black text-emerald-400 flex items-center gap-2">
                    <span>🌐</span>
                    <span>المترجم الأكاديمي والتربوي الدقيق</span>
                </h2>
                <p class="text-xs text-slate-400 mt-0.5">ترجمة علمية رصينة تحافظ على المصطلحات التخصصية، السياق البيداغوجي، والرموز الرياضية.</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
                <div class="md:col-span-2">
                    <div class="flex items-center gap-2 mb-3">
                        <label class="flex-1 min-w-0 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-emerald-500/40 rounded-2xl p-3 text-center flex items-center justify-center gap-2">
                            <span class="text-lg flex-shrink-0">🌍</span>
                            <span id="translatorFileName" class="text-xs font-bold text-slate-200 truncate">ارفع ملفاً أو وثيقة للترجمة (.pdf / .pptx / صورة)</span>
                            <input type="file" id="translatorFileInput" accept=".pdf,.pptx,image/*,.txt" class="hidden" onchange="handleToolFile(this, 'translator')">
                        </label>
                        <button type="button" id="translatorClearBtn" onclick="clearToolFile('translator')" class="hidden flex-shrink-0 px-3.5 py-3 rounded-2xl bg-red-500/20 border border-red-500/30 text-red-300 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="translatorInput" rows="4" placeholder="أو الصق النص الأكاديمي أو التربوي للترجمة..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-emerald-500 outline-none"></textarea>
                </div>
                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-center">
                    <label class="block text-xs font-bold text-emerald-400 mb-2">الترجمة إلى اللغة:</label>
                    <select id="translatorTarget" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="French (Français académique)">الفرنسية الأكاديمية (Français)</option>
                        <option value="Modern Standard Arabic (العربية الفصحى العلمية)">العربية الفصحى العلمية</option>
                        <option value="Academic English">الإنجليزية الأكاديمية (English)</option>
                    </select>
                </div>
            </div>
            <button type="button" onclick="runSmartTool('translator')" id="translatorBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-emerald-600 to-teal-600 font-black text-white text-sm">ترجمة أكاديمية فورية 🌐</button>
        </div>
        <div id="translatorResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box mb-8">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-black text-emerald-400">✅ النص المترجم بالصياغة الأكاديمية</span>
                <div class="flex gap-2">
                    <button type="button" onclick="copyText('translatorOutput')" class="px-3.5 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button type="button" onclick="window.print()" class="px-4 py-1.5 rounded-xl bg-emerald-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
                </div>
            </div>
            <div id="translatorOutput" class="prose-output"></div>
        </div>
    </div>

    <script>
        let stationsCount = 4;
        let ncmBase64 = null, ncmMime = null, ncmUploadedFilename = '';
        let toolFiles = { solver: {}, summarizer: {}, translator: {} };
        let adminTapCounter = 0, adminTapTimer = null;

        const savedKey = localStorage.getItem('gemini_api_key') || '';
        const apiKeyField = document.getElementById('apiKeyInput');
        if (apiKeyField) apiKeyField.value = savedKey;

        // نقرة سرية (5 مرات على شعار القبعة 🎓) لإظهار نافذة مفتاح API للمشرف فقط
        function secretAdminTap() {
            adminTapCounter++;
            clearTimeout(adminTapTimer);
            if (adminTapCounter >= 5) {
                adminTapCounter = 0;
                toggleApiModal();
            } else {
                adminTapTimer = setTimeout(() => { adminTapCounter = 0; }, 1800);
            }
        }

        function formatShortName(name) {
            if (!name) return '';
            if (name.length <= 32) return name;
            const ext = name.includes('.') ? '.' + name.split('.').pop() : '';
            return name.substring(0, 22) + '...' + ext;
        }

        function switchSection(secId) {
            document.querySelectorAll('.app-section').forEach(el => el.classList.remove('active-section'));
            const targetSec = document.getElementById('sec-' + secId);
            if (targetSec) targetSec.classList.add('active-section');

            document.querySelectorAll('.nav-card').forEach(b => b.classList.remove('active', 'border-cyan-500/50'));
            const activeCard = document.getElementById('card-' + secId);
            if (activeCard) activeCard.classList.add('active');

            if (secId === 'ncm') setTimeout(drawConnectors, 60);
        }

        function setStations(num) {
            stationsCount = parseInt(num, 10);
            document.querySelectorAll('.st-btn').forEach(b => b.classList.remove('active-st'));
            const activeBtn = document.getElementById('st-btn-' + num);
            if (activeBtn) activeBtn.classList.add('active-st');
        }

        function toggleApiModal() {
            document.getElementById('apiModal').classList.toggle('hidden');
        }

        function saveApiKey() {
            localStorage.setItem('gemini_api_key', document.getElementById('apiKeyInput').value.trim());
            toggleApiModal();
            alert('تم حفظ مفتاح الخدمة بنجاح!');
        }

        function renderFormattedOutput(elementId, rawMarkdown) {
            const el = document.getElementById(elementId);
            if (!el) return;
            const mathBlocks = [];
            let protectedText = (rawMarkdown || '')
                .replace(/\$\$[\s\S]*?\$\$/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; })
                .replace(/\\\[[\s\S]*?\\\]/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; })
                .replace(/\\\([\s\S]*?\\\)/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; })
                .replace(/\$([^\$\r\n]+?)\$/g, match => { mathBlocks.push(match); return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`; });

            let html = (typeof marked !== 'undefined') ? marked.parse(protectedText) : protectedText;
            html = html.replace(/@@MATH_BLOCK_(\d+)@@/g, (_, idx) => mathBlocks[parseInt(idx, 10)]);

            const arabicChars = (rawMarkdown.match(/[\u0600-\u06FF]/g) || []).length;
            const latinChars = (rawMarkdown.match(/[a-zA-Z]/g) || []).length;
            el.setAttribute('dir', arabicChars >= latinChars ? 'rtl' : 'ltr');
            el.innerHTML = html;
            if (window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise([el]).catch(() => {});
            }
        }

        function compressImageFile(file, callback) {
            const reader = new FileReader();
            reader.onload = e => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    const maxDim = 1500;
                    let w = img.width, h = img.height;
                    if (w > maxDim || h > maxDim) {
                        if (w > h) { h = Math.round(h * maxDim / w); w = maxDim; }
                        else { w = Math.round(w * maxDim / h); h = maxDim; }
                    }
                    canvas.width = w; canvas.height = h;
                    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                    callback(canvas.toDataURL('image/jpeg', 0.86).split(',')[1], 'image/jpeg');
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        }

        async function handleNcmFile(input) {
            const file = input.files[0];
            if (!file) return;
            ncmUploadedFilename = file.name;
            document.getElementById('ncmFileName').innerText = "✅ " + formatShortName(file.name);
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
            document.getElementById('ncmFileName').innerText = 'اختر ملف الدرس (.pptx / .pdf / صورة)';
            document.getElementById('ncmClearBtn').classList.add('hidden');
            ncmBase64 = null; ncmMime = null;
        }

        async function handleToolFile(input, toolKey) {
            const file = input.files[0];
            if (!file) return;
            document.getElementById(toolKey + 'FileName').innerText = "✅ " + formatShortName(file.name);
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
            document.getElementById(toolKey + 'FileName').innerText = 'ارفع ملفاً أو صورة (.pdf / .pptx / صورة)';
            document.getElementById(toolKey + 'ClearBtn').classList.add('hidden');
        }

        async function generateNCM() {
            const text = document.getElementById('ncmTextInput').value.trim();
            const ncmNum = document.getElementById('ncmNumInput').value.trim() || '10';
            const apiKey = localStorage.getItem('gemini_api_key');
            if (!text && !ncmBase64) return alert('يرجى رفع ملف الدرس أو لصق محتواه أولاً.');
            const btn = document.getElementById('ncmGenBtn');
            const origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ جاري تصميم وهيكلة الخطاطة التربوية...</span>';
            try {
                const res = await fetch('/generate_ncm', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        text, filename: ncmUploadedFilename, stations: stationsCount, ncm_num: ncmNum,
                        meta_overrides: {
                            level: document.getElementById('metaLevel').value.trim(),
                            periode: document.getElementById('metaPeriode').value.trim(),
                            unite: document.getElementById('metaUnite').value.trim(),
                            semaine: document.getElementById('metaSemaine').value.trim(),
                            seance: document.getElementById('metaSeance').value.trim()
                        },
                        file_b64: ncmBase64, mime_type: ncmMime, api_key: apiKey
                    })
                });
                const data = await res.json();
                if (data.error) { alert(data.error); if (data.need_key) toggleApiModal(); }
                else { renderNCMSheet(data.result, ncmNum); }
            } catch(e) { alert('خطأ في الاتصال بالخادم.'); }
            finally { btn.disabled = false; btn.innerHTML = origHtml; }
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
            const seanceBadge = d.seance_ncm_badge || (isFr ? `Fiche N° ${d.ncm_number || ncmNum}` : `خطاطة رقم (${d.ncm_number || ncmNum})`);
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
            document.getElementById('hdrBadgeLabel').innerText = isFr ? 'FICHE N°' : 'خطاطة رقم';
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
            if (!text && !fileObj.b64) return alert('يرجى إدخال النص أو رفع ملف/صورة أولاً.');
            const btn = document.getElementById(toolType + 'Btn');
            const origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ جاري التحليل المعمّق وصياغة الحل...</span>';

            let extraOptions = {};
            if (toolType === 'solver') {
                extraOptions = {
                    domain: document.getElementById('solverDomain').value,
                    depth: document.getElementById('solverDepth').value,
                    lang: document.getElementById('solverLang').value
                };
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
            } catch(e) { alert('خطأ في الاتصال بالخادم.'); }
            finally { btn.disabled = false; btn.innerHTML = origHtml; }
        }

        function copyText(elId) {
            navigator.clipboard.writeText(document.getElementById(elId).innerText);
            alert('تم نسخ المحتوى بنجاح!');
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
    if 'file' not in request.files:
        return jsonify({'error': 'لم يتم إرفاق ملف'})
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

    if not api_key:
        return jsonify({'error': 'يرجى إدخال مفتاح API (بالنقر 5 مرات على شعار القبعة 🎓 أعلى اليمين).', 'need_key': True})

    fn_meta = parse_filename_metadata(filename)
    lvl = overrides.get('level') or fn_meta.get('level') or ''
    per = overrides.get('periode') or fn_meta.get('periode') or ''
    uni = overrides.get('unite') or fn_meta.get('unite') or ''
    sem = overrides.get('semaine') or fn_meta.get('semaine') or ''
    sea = overrides.get('seance') or fn_meta.get('seance') or ''

    is_fr = filename.upper().startswith('FR') or (text and len(re.findall(r'[a-zA-Zéèêëàâîïôùûç]', text[:2000])) > len(re.findall(r'[\u0600-\u06FF]', text[:2000])))

    if is_fr:
        system_prompt = f"""Tu es un inspecteur pédagogique expert de l'Enseignement Explicite (École Pionnière au Maroc).
RÈGLE DE LANGUE : Réponds 100% en FRANÇAIS ("lang": "fr"). Zéro mot en arabe ! N'utilise jamais l'acronyme NCM.
Format header_title : "Français – Niveau {lvl or 'X'} | Période {per or 'P'} - Unité {uni or 'U'} - Semaine {sem or 'W'} - Séance {sea or 'S'}"
Format lesson_subtitle : "Enseignement explicite | [Titre de la leçon] (Livret : p. ...)"
Divise en EXACTEMENT ({stations}) stations méthodologiques avec des durées réelles (ex: 15 min).
Retourne UNIQUEMENT un JSON valide :
{{"lang":"fr","ncm_number":"{ncm_num}","header_title":"...","lesson_subtitle":"...","objectives":"...","subject_level":"Français N{lvl or '2'}","unit_week":"Période {per or '2'} - Unité {uni or '1'} | Semaine {sem or '2'}","seance_ncm_badge":"Séance {sea or '4'} (Fiche {ncm_num})","livret_pages":"Livret : p. ...","stations":[{{"title":"...","duration":"15 min","bullets":[{{"label":"...","text":"..."}}]}}]}}"""
    else:
        system_prompt = f"""أنت مفتش وخبير بيداغوجي في برنامج التعليم الصريح بالمدرسة الرائدة.
قاعدة اللغة: رد باللغة العربية الفصحى 100% ("lang": "ar").
header_title: "[المادة] – المستوى {lvl or '2'} | المرحلة {per or '2'} - الوحدة {uni or '1'} - الأسبوع {sem or '2'} - الحصة {sea or '4'}"
lesson_subtitle: "برنامج التعليم الصريح | [عنوان الدرس] (الكراسة: ص. ...)"
قسّم الدرس إلى ({stations}) محطات منهجية دقيقة مع مدد زمنية حقيقية (مثال: 15 د).
أرجع JSON صالحاً فقط:
{{"lang":"ar","ncm_number":"{ncm_num}","header_title":"...","lesson_subtitle":"...","objectives":"...","subject_level":"اللغة العربية {lvl or '2'}","unit_week":"المرحلة {per or '2'} – الوحدة {uni or '1'} | الأسبوع {sem or '2'}","seance_ncm_badge":"الحصة {sea or '4'} (خطاطة {ncm_num})","livret_pages":"الكراسة: ص. ...","stations":[{{"title":"...","duration":"15 د","bullets":[{{"label":"...","text":"..."}}]}}]}}"""

    parts = [{"text": system_prompt + "\n\nContent:\n" + (text[:35000] if text else "Analyze attached file.")}]
    if file_b64 and mime_type:
        parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    raw_text, err = call_gemini_api(api_key, parts, json_mode=True, temperature=0.1)
    if err or not raw_text:
        return jsonify({'error': f'تعذر التوليد: {err}'})
    try:
        res_json = json.loads(re.search(r'\{[\s\S]*\}', raw_text).group(0))
        if 'stations' in res_json:
            res_json['stations'] = res_json['stations'][:stations]
        return jsonify({'result': res_json})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/smart_tool', methods=['POST'])
def smart_tool():
    data = request.get_json(force=True)
    tool = data.get('tool')
    text = data.get('text', '')
    options = data.get('options') or {}
    file_b64 = data.get('file_b64')
    mime_type = data.get('mime_type')
    api_key = (data.get('api_key') or os.environ.get('GEMINI_API_KEY') or '').strip()
    if not api_key:
        return jsonify({'error': 'يرجى إدخال مفتاح API (بالنقر 5 مرات على شعار القبعة 🎓 أعلى اليمين).', 'need_key': True})

    lang_opt = options.get('lang', 'auto')
    if lang_opt == 'fr':
        lang_rule = "CRITICAL LANGUAGE RULE: Write your entire response 100% in impeccable Academic FRENCH. Zero Arabic words."
    elif lang_opt == 'ar':
        lang_rule = "CRITICAL LANGUAGE RULE: Write your entire response 100% in impeccable Academic ARABIC."
    elif lang_opt == 'en':
        lang_rule = "CRITICAL LANGUAGE RULE: Write your entire response 100% in impeccable Academic ENGLISH."
    else:
        lang_rule = "CRITICAL LANGUAGE RULE: Detect the language of the attached image/document/problem and respond 100% in that EXACT SAME language (French problem -> 100% French solution; Arabic problem -> 100% Arabic solution; English problem -> 100% English solution). Never mix languages."

    if tool == 'translator':
        target_lang = options.get('target', 'French (Français académique)')
        prompt = f"""You are a world-class academic & scientific translator.
Translate the provided document/image/text into {target_lang} with extreme precision:
1. Preserve the exact academic register, pedagogical terminology, and structure (headings, bullet points, tables).
2. Keep all mathematical equations and symbols properly formatted in LaTeX ($...$ for inline, $$...$$ for display).
3. Deliver a clean, publication-ready translation without meta-commentary."""
    elif tool == 'summarizer':
        prompt = f"""You are an elite university professor and instructional designer.
{lang_rule}
Analyze the input thoroughly and produce an executive, deeply structured academic synthesis:
1. **الإطار العام والهدف المحوري / Vue d'ensemble** : Core thesis and scope of the document.
2. **المفاهيم والقواعد الأساسية / Concepts et règles clés** : Precise definitions, laws, or formulas (using LaTeX $...$ / $$...$$ if applicable).
3. **الهيكلة التفصيلية للمحاور / Synthèse structurée par axes** : Clear hierarchical breakdown of all sections.
4. **خلاصة تركيبية مركزة / Points essentiels à retenir** : High-yield takeaways in a structured table or callout block."""
    else:
        domain = options.get('domain', 'Mathematics & Sciences')
        depth = options.get('depth', 'deep')
        if depth == 'concise':
            depth_instruction = "Provide a direct, laser-focused solution showing the essential equations, key steps, and boxed final result without unnecessary prose."
        elif depth == 'pedagogical':
            depth_instruction = "Provide a pedagogical, learner-friendly breakdown explaining the intuition behind each step, why each theorem is chosen, and how to avoid common mistakes."
        else:
            depth_instruction = """Provide an exhaustive, university/olympiad-grade analytical solution following this exact rigorous architecture for every exercise/question:
- **1. قراءة تحليلية للمعطيات والمطلوب / Analyse des données et de l'objectif** : Explicitly extract given values, domain of definition/validity, and what must be proved or calculated.
- **2. التأصيل النظري والقواعد المعتمدة / Cadre théorique et théorèmes utilisés** : State the exact mathematical/scientific theorems, laws, or formulas before applying them.
- **3. البرهنة والحل المنهجي المفصل / Résolution rigoureuse étape par étape** : Numbered logical steps with zero skipped algebraic or scientific transitions. Format all equations cleanly in LaTeX ($...$ for inline and $$...$$ for standalone equations).
- **4. النتيجة النهائية والتحقق / Conclusion et vérification** : Place the final answer inside a Markdown blockquote (`>`) with bold formatting and proper units, and verify its mathematical/physical consistency.
- **5. إضاءة منهجية / Astuce méthodologique** : A sharp, focused expert insight on the method used."""

        prompt = f"""You are an elite Professor of {domain} and master problem solver.
{lang_rule}
{depth_instruction}
If the input image or text contains multiple questions/sub-questions (e.g., 1, 2, a, b), solve EVERY SINGLE ONE of them completely and systematically."""

    parts = [{"text": prompt + "\n\nInput Content:\n" + (text[:35000] if text else "Carefully transcribe and process the attached image/document.")}]
    if file_b64 and mime_type:
        parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    raw_text, err = call_gemini_api(api_key, parts, json_mode=False, temperature=0.12)
    if err or not raw_text:
        return jsonify({'error': f'خطأ: {err}'})
    return jsonify({'result': raw_text})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
