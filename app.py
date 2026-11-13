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

def get_available_models(api_key, high_rigor=False):
    cache_key = f"{api_key}_{high_rigor}"
    if cache_key in AVAILABLE_MODELS_CACHE and AVAILABLE_MODELS_CACHE[cache_key]:
        return AVAILABLE_MODELS_CACHE[cache_key]
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
                and 'vision' not in m['name'] and 'embedding' not in m['name']
            ]
            prioritized = []
            if high_rigor:
                priority_keywords = ['2.5-pro', '3.1-pro', '3-pro', '2.5-flash', '3-flash', '2.0-flash', 'pro', 'flash']
                for keyword in priority_keywords:
                    for v in valid:
                        if keyword in v and 'lite' not in v and v not in prioritized:
                            prioritized.append(v)
            else:
                priority_keywords = ['2.5-flash', '3-flash', '2.5-pro', '2.0-flash', 'flash', 'pro']
                for keyword in priority_keywords:
                    for v in valid:
                        if keyword in v and 'lite' not in v and v not in prioritized:
                            prioritized.append(v)
            for v in valid:
                if v not in prioritized:
                    prioritized.append(v)
            if prioritized:
                AVAILABLE_MODELS_CACHE[cache_key] = prioritized
                return prioritized
    except Exception:
        pass
    return ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]

def extract_pptx_text(file_stream):
    text_runs = []
    try:
        with zipfile.ZipFile(file_stream) as z:
            namelist = z.namelist()
            slide_files = [f for f in namelist if f.startswith('ppt/slides/slide') and f.endswith('.xml')]
            slide_files.sort(key=lambda x: int(re.search(r'slide(\d+)\.xml', x).group(1)) if re.search(r'slide(\d+)\.xml', x) else 0)
            for idx, slide in enumerate(slide_files, 1):
                tree = ET.fromstring(z.read(slide))
                slide_texts = [elem.text.strip() for elem in tree.iter() if elem.tag.endswith('}t') and elem.text and elem.text.strip()]
                note_file = f"ppt/notesSlides/notesSlide{idx}.xml"
                note_texts = []
                if note_file in namelist:
                    try:
                        ntree = ET.fromstring(z.read(note_file))
                        note_texts = [elem.text.strip() for elem in ntree.iter() if elem.tag.endswith('}t') and elem.text and elem.text.strip()]
                    except Exception:
                        pass
                combined = " | ".join(slide_texts)
                if note_texts:
                    combined += " [Notes: " + " | ".join(note_texts) + "]"
                if combined.strip():
                    text_runs.append(f"[Slide {idx}]: {combined}")
    except Exception as e:
        return f"Error: {str(e)}"
    return "\n".join(text_runs)

def parse_filename_metadata(filename):
    meta = {}
    if not filename:
        return meta
    fn = filename.upper()
    # دعم الأقسام المشتركة مثل N1&2 أو N1_2 أو 1+2
    lvl_joint = re.search(r'(?:N|NIVEAU|AEP)[_-]?(\d\s*[\&\+\-]\s*\d)', fn)
    lvl_single = re.search(r'(?:N|NIVEAU|AEP)[_-]?(\d)', fn) or re.search(r'(\d)AEP', fn)
    per = re.search(r'P(\d)', fn)
    uni = re.search(r'U(\d)', fn)
    sem = re.search(r'SEM[_-]?(\d+)', fn) or re.search(r'W(\d+)', fn)
    sea = re.search(r'_S(\d+)', fn) or re.search(r'SEANCE[_-]?(\d+)', fn)
    ncm = re.search(r'NCM[_-]?(\d+)', fn)
    if lvl_joint:
        meta['level'] = re.sub(r'[\&\-\s]+', '+', lvl_joint.group(1))
    elif lvl_single:
        meta['level'] = lvl_single.group(1)
    if per: meta['periode'] = per.group(1)
    if uni: meta['unite'] = uni.group(1)
    if sem: meta['semaine'] = sem.group(1)
    if sea: meta['seance'] = sea.group(1)
    if ncm: meta['ncm'] = ncm.group(1)
    return meta

def sanitize_ncm_data(res_json):
    is_fr = (res_json.get('lang') or '').lower() == 'fr'
    if 'header_title' in res_json and res_json['header_title']:
        # حذف أي مكونات فرعية بين قوسين مثل (Oral, Lecture, Écriture) من الترويسة
        res_json['header_title'] = re.sub(r'\s*\([^)]*\)', '', res_json['header_title']).strip()
    if is_fr and 'seance_ncm_badge' in res_json and res_json['seance_ncm_badge']:
        res_json['seance_ncm_badge'] = re.sub(r'Fiche(\s*N°)?', 'NCM', res_json['seance_ncm_badge'], flags=re.IGNORECASE)
    unit = "min" if is_fr else "د"
    stations = res_json.get('stations') or []
    for st in stations:
        raw_dur = str(st.get('duration') or '').strip()
        trans = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
        clean_dur = raw_dur.translate(trans)
        nums = re.findall(r'\d+', clean_dur)
        if nums:
            val = int(nums[0])
            if val >= 60:
                val = val // 10 if val >= 100 else 15
            if val > 45:
                val = 20
            if val < 3:
                val = 5
            st['duration'] = f"{val} {unit}"
        else:
            st['duration'] = f"10 {unit}"
    return res_json

def call_gemini_api(api_key, parts, json_mode=False, temperature=0.05, high_rigor=False):
    candidate_models = get_available_models(api_key, high_rigor=high_rigor)
    gen_config = {
        "temperature": temperature,
        "maxOutputTokens": 8192
    }
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
                    timeout=90
                )
                res_data = res.json()
                if res.status_code == 200 and 'candidates' in res_data:
                    return res_data['candidates'][0]['content']['parts'][0]['text'], None
                else:
                    last_error = res_data.get('error', {}).get('message', 'خطأ في الاستجابة')
                    time.sleep(0.4)
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
            chtml: { scale: 1.12 },
            options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre'] }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <style id="dynamicPageStyle">
        @page { size: A4 landscape; margin: 0mm; }
    </style>
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
            background: rgba(15, 23, 42, 0.9);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(148, 163, 184, 0.16);
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
        }
        .app-section { display: none; animation: fadeIn 0.2s ease-out; }
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
            background: linear-gradient(145deg, rgba(14, 165, 233, 0.24), rgba(30, 58, 138, 0.38)) !important;
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

        /* لوحة خطاطة A4 Paysage قياسية (صفحة واحدة متناسقة 100%) */
        .sheet-scroll-viewport {
            width: 100%;
            overflow-x: auto;
            padding-bottom: 14px;
            display: flex;
            justify-content: flex-start;
        }
        @media (min-width: 1150px) {
            .sheet-scroll-viewport { justify-content: center; }
        }
        .ncm-sheet {
            background: #ffffff;
            color: #0f172a;
            border-radius: 14px;
            padding: 14px 18px;
            box-shadow: 0 25px 60px rgba(0,0,0,0.6);
            width: 1122px;
            min-width: 1122px;
            max-width: 1122px;
            height: 685px;
            min-height: 685px;
            max-height: 685px;
            margin: 0 auto;
            position: relative;
            border: 1px solid #cbd5e1;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            overflow: hidden;
        }
        .ncm-top-banner {
            background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%);
            color: white;
            border-radius: 10px;
            padding: 9px 18px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            margin-bottom: 7px;
            border-bottom: 3.5px solid #f59e0b;
            flex-shrink: 0;
        }
        .ncm-orange-badge {
            background: linear-gradient(180deg, #f97316 0%, #ea580c 100%);
            color: white;
            border-radius: 9px;
            padding: 5px 14px;
            text-align: center;
            min-width: 90px;
            box-shadow: 0 3px 10px rgba(0,0,0,0.22);
            border: 1.5px solid rgba(255,255,255,0.45);
            flex-shrink: 0;
        }
        .ncm-objectives-box {
            background: #f8fafc;
            border: 1.5px solid #cbd5e1;
            border-right: 5px solid #2563eb;
            border-radius: 9px;
            padding: 7px 14px;
            margin-bottom: 10px;
            font-size: 13px;
            line-height: 1.5;
            flex-shrink: 0;
        }
        [dir="ltr"] .ncm-objectives-box {
            border-right: 1.5px solid #cbd5e1;
            border-left: 5px solid #2563eb;
        }

        .mindmap-container {
            position: relative;
            z-index: 1;
            width: 100%;
            flex: 1;
            display: flex;
            align-items: stretch;
            min-height: 0;
        }
        #pathSvg {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 1;
            overflow: visible;
        }
        /* شبكة هندسية متوازنة تترك ممراً واضحاً للخطوط الرابطة */
        .ncm-grid-layout {
            position: relative;
            z-index: 2;
            width: 100%;
            height: 100%;
            display: grid;
            grid-template-columns: 1.12fr 0.90fr 1.12fr;
            gap: 32px;
            align-items: stretch;
        }
        .ncm-col {
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 14px;
            height: 100%;
            min-height: 0;
        }
        .ncm-col-center {
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: stretch;
            gap: 14px;
            height: 100%;
            min-height: 0;
        }
        .ncm-col-center.only-hub {
            justify-content: center;
        }

        .station-box {
            background: #ffffff;
            border: 2px solid #cbd5e1;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(15, 23, 42, 0.06);
            display: flex;
            flex-direction: column;
            flex: 0 0 auto;
            height: auto;
        }
        .station-header-bar {
            color: white;
            padding: 6px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            font-weight: 800;
            font-size: var(--st-title-size, 13.5px);
            flex-shrink: 0;
        }
        .station-time-tag {
            background: rgba(0,0,0,0.28);
            color: #ffffff;
            padding: 1.5px 9px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 800;
            border: 1px solid rgba(255,255,255,0.45);
            white-space: nowrap;
            flex-shrink: 0;
        }
        .station-content-body {
            padding: 8px 10px;
            font-size: var(--st-body-size, 12.8px);
            line-height: var(--st-line-height, 1.5);
            background: #ffffff;
            flex: 0 0 auto;
            height: auto;
        }
        .station-bullets-list {
            list-style: none;
            padding: 0;
            margin: 0;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            gap: 6px;
            height: auto;
        }
        .station-bullet-item {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 5px 9px;
            display: flex;
            align-items: flex-start;
            gap: 6px;
            flex: 0 0 auto;
            height: auto;
        }

        .center-hub-box {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 4px;
            flex: 0 0 auto;
            height: auto;
        }
        .center-blue-circle {
            width: var(--hub-size, 204px);
            height: var(--hub-size, 204px);
            border-radius: 50%;
            background: radial-gradient(circle at 35% 30%, #2563eb 0%, #1e3a8a 92%);
            color: white;
            padding: 12px;
            text-align: center;
            border: 5px solid #ffffff;
            outline: 3.5px solid #2563eb;
            box-shadow: 0 12px 28px rgba(37, 99, 235, 0.32);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            position: relative;
            margin: 0 auto;
            flex-shrink: 0;
        }

        [contenteditable="true"]:focus { outline: 2px dashed #f59e0b; background: rgba(245, 158, 11, 0.1); border-radius: 4px; }

        .prose-output {
            line-height: 2.0;
            font-size: 17px;
            color: #f1f5f9;
            width: 100%;
        }
        .prose-output h1, .prose-output h2, .prose-output h3 {
            color: #38bdf8;
            font-weight: 900;
            font-size: 1.25em;
            margin-top: 1.4rem;
            margin-bottom: 0.7rem;
            padding-bottom: 0.35rem;
            border-bottom: 2px solid rgba(56, 189, 248, 0.25);
        }
        .prose-output p { margin-bottom: 0.95rem; }
        .prose-output ul { list-style-type: disc; padding-inline-start: 1.6rem; margin-bottom: 1rem; }
        .prose-output ol { list-style-type: decimal; padding-inline-start: 1.6rem; margin-bottom: 1rem; }
        .prose-output li { margin-bottom: 0.5rem; }
        .prose-output blockquote {
            background: rgba(14, 165, 233, 0.12);
            border-inline-start: 5px solid #38bdf8;
            padding: 14px 18px;
            border-radius: 12px;
            margin: 1.2rem 0;
            font-weight: 700;
            color: #ffffff;
        }
        .prose-output table { width: 100%; border-collapse: collapse; margin: 1.2rem 0; }
        .prose-output th, .prose-output td { border: 1px solid #334155; padding: 10px 14px; font-size: 16px; }
        .prose-output th { background: #1e293b; color: #38bdf8; font-weight: 800; }
        .prose-output strong { color: #fde047; font-weight: 800; }
        mjx-container { overflow-x: auto; overflow-y: hidden; max-width: 100%; padding: 4px 2px; }
        mjx-container[display="true"] {
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 12px;
            padding: 12px 16px;
            margin: 12px 0 !important;
        }

        @media print {
            html, body {
                background: #ffffff !important;
                color: #000000 !important;
                min-height: 0 !important;
                height: auto !important;
                margin: 0 !important;
                padding: 0 !important;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }
            .no-print { display: none !important; }
            .app-section.active-section {
                display: block !important;
                width: 100% !important;
                max-width: 100% !important;
                margin: 0 !important;
                padding: 0 !important;
            }
            html:has(body.printing-ncm), body.printing-ncm {
                width: 1122px !important;
                min-height: 0 !important;
                height: 685px !important;
                max-height: 685px !important;
                margin: 0 !important;
                padding: 0 !important;
                overflow: hidden !important;
            }
            body.printing-ncm #sec-ncm {
                width: 1122px !important;
                max-width: 1122px !important;
                height: 685px !important;
                max-height: 685px !important;
                margin: 0 !important;
                padding: 0 !important;
                overflow: hidden !important;
            }
            body.printing-ncm .sheet-scroll-viewport {
                overflow: hidden !important;
                display: block !important;
                width: 1122px !important;
                height: 685px !important;
                max-height: 685px !important;
                padding: 0 !important;
                margin: 0 !important;
                page-break-after: avoid !important;
                page-break-inside: avoid !important;
            }
            body.printing-ncm .ncm-sheet {
                box-shadow: none !important;
                border: none !important;
                border-radius: 0 !important;
                width: 1122px !important;
                min-width: 1122px !important;
                max-width: 1122px !important;
                height: 685px !important;
                min-height: 685px !important;
                max-height: 685px !important;
                padding: 10px 14px !important;
                margin: 0 !important;
                page-break-after: avoid !important;
                page-break-inside: avoid !important;
                break-inside: avoid !important;
            }
            .prose-print-box {
                background: #ffffff !important;
                color: #000000 !important;
                border: none !important;
                box-shadow: none !important;
                padding: 0 !important;
                margin: 0 !important;
                width: 100% !important;
                max-width: 100% !important;
            }
            .prose-output {
                font-size: 13.5pt !important;
                line-height: 1.75 !important;
                color: #000000 !important;
                width: 100% !important;
            }
            .prose-output p, .prose-output li, .prose-output td {
                color: #000000 !important;
                font-size: 13.5pt !important;
            }
            .prose-output h1, .prose-output h2, .prose-output h3 {
                color: #1e3a8a !important;
                font-size: 15.5pt !important;
                border-bottom: 1.5px solid #94a3b8 !important;
                margin-top: 14pt !important;
                margin-bottom: 6pt !important;
                page-break-after: avoid;
            }
            .prose-output strong {
                color: #000000 !important;
                font-weight: 900 !important;
            }
            .prose-output blockquote {
                background: #f1f5f9 !important;
                border-inline-start: 4px solid #1e3a8a !important;
                color: #000000 !important;
                padding: 10px 14px !important;
                page-break-inside: avoid;
            }
            mjx-container[display="true"] {
                background: #f8fafc !important;
                border: 1px solid #cbd5e1 !important;
                padding: 8px 12px !important;
                margin: 8px 0 !important;
                page-break-inside: avoid;
            }
        }
    </style>
</head>
<body class="p-3 md:p-6">
    <div class="max-w-6xl mx-auto no-print mb-6">
        <header class="glass-panel p-4 rounded-3xl flex items-center justify-between gap-4">
            <div class="flex items-center gap-3.5">
                <div onclick="secretAdminTap()" class="w-12 h-12 rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg cursor-pointer select-none">
                    <span class="text-2xl">🎓</span>
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="text-base md:text-lg font-black text-white tracking-wide">الأكاديمية الذكية <span class="text-cyan-400">Pro</span></h1>
                    </div>
                    <p class="text-[11px] text-slate-400">منصة التخطيط التربوي والدعم الأكاديمي</p>
                </div>
            </div>
            <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/25">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span class="text-[11px] font-bold text-emerald-300">متصل</span>
            </div>
        </header>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3.5">
            <button type="button" onclick="switchSection('ncm')" id="card-ncm" class="nav-card active p-3.5 rounded-2xl bg-slate-900/90 border border-cyan-500/50 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">🗺️</span>
                <span class="text-xs font-black text-white">خطاطات الدروس</span>
                <span class="text-[10px] text-slate-400 font-semibold">المدرسة الرائدة • التعليم الصريح</span>
            </button>
            <button type="button" onclick="switchSection('solver')" id="card-solver" class="nav-card p-3.5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">📐</span>
                <span class="text-xs font-black text-slate-100">حل المسائل والتمارين</span>
                <span class="text-[10px] text-slate-400 font-semibold">تحليل علمي • خطوة بخطوة</span>
            </button>
            <button type="button" onclick="switchSection('summarizer')" id="card-summarizer" class="nav-card p-3.5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">📑</span>
                <span class="text-xs font-black text-slate-100">تلخيص المحاضرات والدروس</span>
                <span class="text-[10px] text-slate-400 font-semibold">هيكلة المحاور والمفاهيم</span>
            </button>
            <button type="button" onclick="switchSection('translator')" id="card-translator" class="nav-card p-3.5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-md flex flex-col items-center text-center gap-1">
                <span class="text-2xl">🌐</span>
                <span class="text-xs font-black text-slate-100">الترجمة الأكاديمية</span>
                <span class="text-[10px] text-slate-400 font-semibold">ترجمة علمية وتربوية</span>
            </button>
        </div>

        <div id="apiModal" class="hidden fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
            <div class="glass-panel p-6 rounded-3xl max-w-md w-full border border-blue-500/40">
                <h3 class="text-base font-bold mb-2 text-cyan-400">إعداد مفتاح الخدمة السحابية</h3>
                <input type="password" id="apiKeyInput" placeholder="أدخل مفتاح Gemini API هنا..." class="w-full p-3 rounded-xl bg-slate-900 border border-slate-700 text-white mb-4 text-left font-mono text-sm" dir="ltr">
                <div class="flex justify-end gap-2">
                    <button type="button" onclick="toggleApiModal()" class="px-4 py-2 rounded-xl bg-slate-800 text-xs font-bold">إغلاق</button>
                    <button type="button" onclick="saveApiKey()" class="px-5 py-2 rounded-xl bg-blue-600 text-white font-black text-xs">حفظ وتفعيل</button>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== القسم 1: خطاطات الدروس ==================== -->
    <div id="sec-ncm" class="app-section active-section max-w-6xl mx-auto">
        <div class="glass-panel rounded-3xl p-5 shadow-2xl mb-6 no-print">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-5">
                <div class="lg:col-span-2">
                    <label class="block text-xs font-bold text-cyan-400 mb-2">1. ملف الدرس أو المحتوى:</label>
                    <div class="flex items-center gap-2 mb-2.5">
                        <label class="flex-1 min-w-0 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-cyan-500/50 rounded-2xl p-3 text-center transition flex items-center justify-center gap-2">
                            <span class="text-lg flex-shrink-0">📂</span>
                            <span id="ncmFileName" class="text-xs font-bold text-slate-200 truncate">اختر ملف الدرس (.pptx / .pdf / صورة)</span>
                            <input type="file" id="ncmFileInput" accept=".pptx,.ppt,.pdf,image/*,.txt" class="hidden" onchange="handleNcmFile(this)">
                        </label>
                        <button type="button" id="ncmClearBtn" onclick="clearNcmFile()" class="hidden flex-shrink-0 px-3.5 py-3 rounded-2xl bg-red-500/20 border border-red-500/30 text-red-300 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="ncmTextInput" rows="3" placeholder="أو الصق محتوى الدرس أو الجذاذة هنا..." class="w-full p-3 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-cyan-500 outline-none"></textarea>
                </div>

                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-between">
                    <div>
                        <label class="block text-xs font-bold text-cyan-400 mb-2">2. عدد المحطات وبيانات الترويسة:</label>
                        <div class="grid grid-cols-6 gap-1.5 mb-3">
                            <button type="button" onclick="setStations(0)" id="st-btn-0" class="st-btn active-st py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-[11px] text-white">تلقائي</button>
                            <button type="button" onclick="setStations(2)" id="st-btn-2" class="st-btn py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">2</button>
                            <button type="button" onclick="setStations(3)" id="st-btn-3" class="st-btn py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">3</button>
                            <button type="button" onclick="setStations(4)" id="st-btn-4" class="st-btn py-2 rounded-xl border border-slate-700 bg-slate-800 font-black text-xs text-white">4</button>
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
                            <input id="ncmNumInput" type="text" value="" placeholder="رقم الخطاطة" class="p-1.5 rounded-lg bg-slate-800 border border-amber-500/50 text-center font-black text-[11px] text-amber-300">
                        </div>
                    </div>
                </div>
            </div>

            <button type="button" onclick="generateNCM()" id="ncmGenBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 via-indigo-600 to-cyan-500 border border-cyan-300/30 font-black text-white text-sm tracking-wide flex items-center justify-center gap-2">
                <span>توليد الخطاطة البيداغوجية</span>
                <span class="text-base">⚡</span>
            </button>
        </div>

        <div id="printBar" class="hidden mb-3 flex flex-wrap items-center justify-between gap-2 glass-panel px-4 py-2.5 rounded-2xl no-print">
            <span class="text-xs font-bold text-emerald-400">✅ الخطاطة البيداغوجية جاهزة للتعديل المباشر والطباعة</span>
            <button type="button" onclick="printDocument('landscape')" class="px-5 py-2 rounded-xl bg-emerald-600 text-xs font-black text-white shadow-lg">🖨️ تصدير PDF / طباعة</button>
        </div>

        <div id="sheetWrapper" class="hidden sheet-scroll-viewport">
            <div id="ncmSheet" class="ncm-sheet" dir="rtl">
                <div class="ncm-top-banner">
                    <div class="flex-1">
                        <div id="hdrTitle" contenteditable="true" class="text-[15px] font-black text-white leading-snug mb-0.5"></div>
                        <div id="hdrSub" contenteditable="true" class="text-xs font-bold text-amber-200"></div>
                    </div>
                    <div class="ncm-orange-badge">
                        <div id="hdrBadgeLabel" class="text-[10px] font-bold uppercase opacity-95">خطاطة رقم</div>
                        <div id="hdrBadgeNum" contenteditable="true" class="text-xl font-black leading-none mt-0.5">10</div>
                    </div>
                </div>

                <div class="ncm-objectives-box">
                    <span id="objLabel" class="font-black text-slate-900">أهداف التعلم: </span>
                    <span id="objText" contenteditable="true" class="text-slate-700 font-semibold"></span>
                </div>

                <div id="mindmapContainer" class="mindmap-container">
                    <svg id="pathSvg" dir="ltr"></svg>
                    <div class="ncm-grid-layout">
                        <div id="colFirst" class="ncm-col"></div>
                        <div id="colCenter" class="ncm-col-center"></div>
                        <div id="colLast" class="ncm-col"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== القسم 2: حل المسائل والتمارين ==================== -->
    <div id="sec-solver" class="app-section max-w-6xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <div class="flex flex-wrap items-center justify-between gap-2 mb-4 pb-3 border-b border-slate-800">
                <div>
                    <h2 class="text-base md:text-lg font-black text-cyan-400 flex items-center gap-2">
                        <span>📐</span>
                        <span>حل المسائل والتمارين العلمية</span>
                    </h2>
                    <p class="text-xs text-slate-400 mt-0.5">تحليل منهجي متكامل للمسائل الرياضية والعلمية مع صياغة الخطوات بالتفصيل.</p>
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
                    <textarea id="solverInput" rows="4" placeholder="أو اكتب نص المسألة أو المعادلات هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-cyan-500 outline-none"></textarea>
                </div>

                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-between gap-2">
                    <div>
                        <label class="block text-[11px] font-bold text-cyan-400 mb-1">التخصص:</label>
                        <select id="solverDomain" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-2.5">
                            <option value="Mathematics (Algebra, Analysis, Geometry, Probability)">الرياضيات</option>
                            <option value="Physics, Mechanics, Electromagnetism & Chemistry">الفيزياء والكيمياء</option>
                            <option value="Life & Earth Sciences (SVT) & Engineering">علوم الحياة والأرض والهندسة</option>
                            <option value="Languages, Grammar & Literature">اللغات والدراسات الأدبية</option>
                        </select>

                        <label class="block text-[11px] font-bold text-cyan-400 mb-1">مستوى التفصيل:</label>
                        <select id="solverDepth" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-2.5">
                            <option value="deep">حل مفصل وشامل</option>
                            <option value="pedagogical">شرح تعليمي مبسط</option>
                            <option value="concise">حل مختصر ومباشر</option>
                        </select>

                        <label class="block text-[11px] font-bold text-cyan-400 mb-1">لغة الإجابة:</label>
                        <select id="solverLang" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                            <option value="auto">تلقائي (نفس لغة التمرين)</option>
                            <option value="fr">الفرنسية (Français)</option>
                            <option value="ar">العربية</option>
                            <option value="en">الإنجليزية (English)</option>
                        </select>
                    </div>
                </div>
            </div>

            <button type="button" onclick="runSmartTool('solver')" id="solverBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-cyan-600 via-blue-600 to-indigo-600 border border-cyan-300/30 font-black text-white text-sm flex items-center justify-center gap-2">
                <span>حل المسألة وعرض الخطوات</span>
                <span>⚡</span>
            </button>
        </div>

        <div id="solverResultBox" class="hidden glass-panel rounded-3xl p-6 md:p-8 prose-print-box mb-8">
            <div class="flex flex-wrap justify-between items-center border-b border-slate-700/80 pb-3 mb-5 no-print gap-2">
                <div class="flex items-center gap-2">
                    <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                    <span class="text-xs font-black text-emerald-400">الحل المفصل</span>
                </div>
                <div class="flex gap-2">
                    <button type="button" onclick="copyText('solverOutput')" class="px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-600 text-xs font-bold text-slate-200">📋 نسخ</button>
                    <button type="button" onclick="printDocument('portrait')" class="px-4 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-xs font-black text-white">🖨️ تصدير PDF / طباعة</button>
                </div>
            </div>
            <div id="solverOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 3: تلخيص المحاضرات والدروس ==================== -->
    <div id="sec-summarizer" class="app-section max-w-6xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <div class="mb-4 pb-3 border-b border-slate-800">
                <h2 class="text-base md:text-lg font-black text-amber-400 flex items-center gap-2">
                    <span>📑</span>
                    <span>تلخيص المحاضرات والدروس</span>
                </h2>
                <p class="text-xs text-slate-400 mt-0.5">استخلاص المحاور الأساسية والمفاهيم والقواعد في ملخص منظم.</p>
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
                    <textarea id="summarizerInput" rows="4" placeholder="أو الصق النص المراد تلخيصه هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-amber-500 outline-none"></textarea>
                </div>
                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-center">
                    <label class="block text-xs font-bold text-amber-400 mb-2">لغة الملخص:</label>
                    <select id="summarizerLang" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="auto">تلقائي (نفس لغة الملف)</option>
                        <option value="fr">الفرنسية (Français)</option>
                        <option value="ar">العربية</option>
                        <option value="en">الإنجليزية (English)</option>
                    </select>
                </div>
            </div>
            <button type="button" onclick="runSmartTool('summarizer')" id="summarizerBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-amber-500 to-orange-600 font-black text-slate-950 text-sm">إعداد الملخص المنظم ✨</button>
        </div>
        <div id="summarizerResultBox" class="hidden glass-panel rounded-3xl p-6 md:p-8 prose-print-box mb-8">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-5 no-print">
                <span class="text-xs font-black text-amber-400">✅ الملخص المنظم</span>
                <div class="flex gap-2">
                    <button type="button" onclick="copyText('summarizerOutput')" class="px-3.5 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button type="button" onclick="printDocument('portrait')" class="px-4 py-1.5 rounded-xl bg-amber-600 text-xs font-bold text-white">🖨️ تصدير PDF / طباعة</button>
                </div>
            </div>
            <div id="summarizerOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 4: الترجمة الأكاديمية ==================== -->
    <div id="sec-translator" class="app-section max-w-6xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <div class="mb-4 pb-3 border-b border-slate-800">
                <h2 class="text-base md:text-lg font-black text-emerald-400 flex items-center gap-2">
                    <span>🌐</span>
                    <span>الترجمة الأكاديمية والتربوية</span>
                </h2>
                <p class="text-xs text-slate-400 mt-0.5">ترجمة دقيقة تحافظ على المصطلحات التخصصية والرموز العلمية.</p>
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
                    <textarea id="translatorInput" rows="4" placeholder="أو الصق النص المراد ترجمته هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:border-emerald-500 outline-none"></textarea>
                </div>
                <div class="bg-slate-900/75 p-4 rounded-2xl border border-slate-800 flex flex-col justify-center">
                    <label class="block text-xs font-bold text-emerald-400 mb-2">الترجمة إلى:</label>
                    <select id="translatorTarget" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="French (Français académique)">الفرنسية (Français)</option>
                        <option value="Modern Standard Arabic (العربية الفصحى)">العربية</option>
                        <option value="Academic English">الإنجليزية (English)</option>
                    </select>
                </div>
            </div>
            <button type="button" onclick="runSmartTool('translator')" id="translatorBtn" class="cta-btn w-full py-4 rounded-2xl bg-gradient-to-r from-emerald-600 to-teal-600 font-black text-white text-sm">ترجمة النص 🌐</button>
        </div>
        <div id="translatorResultBox" class="hidden glass-panel rounded-3xl p-6 md:p-8 prose-print-box mb-8">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-5 no-print">
                <span class="text-xs font-black text-emerald-400">✅ النص المترجم</span>
                <div class="flex gap-2">
                    <button type="button" onclick="copyText('translatorOutput')" class="px-3.5 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button type="button" onclick="printDocument('portrait')" class="px-4 py-1.5 rounded-xl bg-emerald-600 text-xs font-bold text-white">🖨️ تصدير PDF / طباعة</button>
                </div>
            </div>
            <div id="translatorOutput" class="prose-output"></div>
        </div>
    </div>

    <script>
        let stationsCount = 0;
        let ncmBase64 = null, ncmMime = null, ncmUploadedFilename = '';
        let toolFiles = { solver: {}, summarizer: {}, translator: {} };
        let adminTapCounter = 0, adminTapTimer = null;

        const savedKey = localStorage.getItem('gemini_api_key') || '';
        const apiKeyField = document.getElementById('apiKeyInput');
        if (apiKeyField) apiKeyField.value = savedKey;

        function fitNcmToSinglePage() {
            const sheet = document.getElementById('ncmSheet');
            const container = document.getElementById('mindmapContainer');
            if (!sheet || !container) return;
            const cardsCount = sheet.querySelectorAll('.station-box').length;
            let bodySize = cardsCount >= 6 ? 11.8 : (cardsCount === 5 ? 12.5 : 13.2);
            let titleSize = cardsCount >= 6 ? 12.6 : 13.5;
            let lineHeight = cardsCount >= 6 ? 1.42 : 1.50;
            let hubSize = cardsCount >= 5 ? 184 : 200;

            sheet.style.setProperty('--st-body-size', bodySize + 'px');
            sheet.style.setProperty('--st-title-size', titleSize + 'px');
            sheet.style.setProperty('--st-line-height', lineHeight);
            sheet.style.setProperty('--hub-size', hubSize + 'px');

            const cols = [document.getElementById('colFirst'), document.getElementById('colCenter'), document.getElementById('colLast')];
            for (let step = 0; step < 12; step++) {
                const maxH = container.clientHeight || 540;
                const colOverflow = cols.some(c => c && c.scrollHeight > maxH + 2);
                if (!colOverflow && sheet.scrollHeight <= 685) break;
                bodySize = Math.max(9.8, bodySize - 0.35);
                titleSize = Math.max(11.0, titleSize - 0.25);
                lineHeight = Math.max(1.28, lineHeight - 0.03);
                hubSize = Math.max(156, hubSize - 5);
                sheet.style.setProperty('--st-body-size', bodySize + 'px');
                sheet.style.setProperty('--st-title-size', titleSize + 'px');
                sheet.style.setProperty('--st-line-height', lineHeight);
                sheet.style.setProperty('--hub-size', hubSize + 'px');
            }
            requestAnimationFrame(drawConnectors);
        }

        function printDocument(orientation) {
            if (ncmUploadedFilename && orientation === 'landscape') {
                document.title = ncmUploadedFilename.replace(/\.[^/.]+$/, '');
            } else if (orientation === 'landscape') {
                const hdr = document.getElementById('hdrTitle')?.innerText?.trim();
                if (hdr) document.title = hdr;
            }
            const styleEl = document.getElementById('dynamicPageStyle');
            if (orientation === 'landscape') {
                document.body.classList.add('printing-ncm');
                styleEl.innerHTML = '@page { size: 297mm 210mm; margin: 0mm; }';
                fitNcmToSinglePage();
            } else {
                document.body.classList.remove('printing-ncm');
                styleEl.innerHTML = '@page { size: A4 portrait; margin: 10mm; }';
            }
            setTimeout(() => {
                drawConnectors();
                window.print();
                setTimeout(() => {
                    document.body.classList.remove('printing-ncm');
                    drawConnectors();
                }, 400);
            }, 140);
        }

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

        function autofillMetaFromFilename(filename) {
            if (!filename) return;
            const fn = filename.toUpperCase();
            const lvlJoint = fn.match(/(?:N|NIVEAU|AEP)[_-]?(\d\s*[\&\+\-]\s*\d)/);
            const lvlSingle = fn.match(/(?:N|NIVEAU|AEP)[_-]?(\d)/) || fn.match(/(\d)AEP/);
            const per = fn.match(/P(\d)/);
            const uni = fn.match(/U(\d)/);
            const sem = fn.match(/SEM[_-]?(\d+)/) || fn.match(/W(\d+)/);
            const sea = fn.match(/_S(\d+)/) || fn.match(/SEANCE[_-]?(\d+)/);
            if (lvlJoint && !document.getElementById('metaLevel').value) {
                document.getElementById('metaLevel').value = lvlJoint[1].replace(/[\&\-\s]+/g, '+');
            } else if (lvlSingle && !document.getElementById('metaLevel').value) {
                document.getElementById('metaLevel').value = lvlSingle[1];
            }
            if (per && !document.getElementById('metaPeriode').value) document.getElementById('metaPeriode').value = per[1];
            if (uni && !document.getElementById('metaUnite').value) document.getElementById('metaUnite').value = uni[1];
            if (sem && !document.getElementById('metaSemaine').value) document.getElementById('metaSemaine').value = sem[1];
            if (sea && !document.getElementById('metaSeance').value) document.getElementById('metaSeance').value = sea[1];
            const ncmMatch = fn.match(/NCM[_-]?(\d+)/) || fn.match(/FICHE[_-]?(\d+)/);
            if (ncmMatch && !document.getElementById('ncmNumInput').value) {
                document.getElementById('ncmNumInput').value = ncmMatch[1];
            }
        }

        function switchSection(secId) {
            document.querySelectorAll('.app-section').forEach(el => el.classList.remove('active-section'));
            const targetSec = document.getElementById('sec-' + secId);
            if (targetSec) targetSec.classList.add('active-section');

            document.querySelectorAll('.nav-card').forEach(b => b.classList.remove('active', 'border-cyan-500/50'));
            const activeCard = document.getElementById('card-' + secId);
            if (activeCard) activeCard.classList.add('active');

            if (secId === 'ncm') setTimeout(fitNcmToSinglePage, 60);
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
            alert('تم حفظ المفتاح بنجاح.');
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
                    const maxDim = 1800;
                    let w = img.width, h = img.height;
                    if (w > maxDim || h > maxDim) {
                        if (w > h) { h = Math.round(h * maxDim / w); w = maxDim; }
                        else { w = Math.round(w * maxDim / h); h = maxDim; }
                    }
                    canvas.width = w; canvas.height = h;
                    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                    callback(canvas.toDataURL('image/jpeg', 0.90).split(',')[1], 'image/jpeg');
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        }

        async function handleNcmFile(input) {
            const file = input.files[0];
            if (!file) return;
            ncmUploadedFilename = file.name;
            document.title = file.name.replace(/\.[^/.]+$/, '');
            autofillMetaFromFilename(file.name);
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
            ['metaLevel','metaPeriode','metaUnite','metaSemaine','metaSeance','ncmNumInput'].forEach(id => document.getElementById(id).value = '');
            ncmBase64 = null; ncmMime = null; ncmUploadedFilename = '';
            document.title = 'الأكاديمية الذكية Pro';
        }

        async function handleToolFile(input, toolKey) {
            const file = input.files[0];
            if (!file) return;
            document.getElementById(toolKey + 'FileName').innerText = "✅ " + formatShortName(file.name);
            document.title = file.name.replace(/\.[^/.]+$/, '');
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
            const ncmNum = document.getElementById('ncmNumInput').value.trim() || '';
            const apiKey = localStorage.getItem('gemini_api_key');
            if (!text && !ncmBase64) return alert('يرجى رفع ملف الدرس أو لصق محتواه أولاً.');
            const btn = document.getElementById('ncmGenBtn');
            const origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ جاري قراءة الدرس وتصميم الخطاطة البيداغوجية...</span>';
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

        function createStationCard(st, idx, isFr) {
            const color = stationColors[idx % stationColors.length];
            const cleanTitle = (st.title || '').replace(/^\d+[\.\-\s]*/, '');
            const borderSide = isFr ? `border-left: 3.5px solid ${color};` : `border-right: 3.5px solid ${color};`;
            const bulletsHtml = (st.bullets || []).map(b => `
                <li class="station-bullet-item" style="${borderSide}">
                    <span style="color: ${color};" class="font-black text-sm leading-none mt-1">●</span>
                    <div contenteditable="true" class="flex-1">
                        ${b.label ? `<strong class="text-slate-900 font-extrabold">${b.label} : </strong>` : ''}
                        <span class="text-slate-700 font-semibold">${b.text || ''}</span>
                    </div>
                </li>
            `).join('');
            return `<div class="station-box" data-st-idx="${idx}" style="border-top: 4px solid ${color};"><div class="station-header-bar" style="background: ${color};"><span contenteditable="true">${idx + 1}. ${cleanTitle}</span>${st.duration ? `<span contenteditable="true" class="station-time-tag">⏱ ${st.duration}</span>` : ''}</div><div class="station-content-body"><ul class="station-bullets-list">${bulletsHtml}</ul></div></div>`;
        }

        function createCenterHub(d, isFr, ncmNum) {
            const tag1 = isFr ? "Enseignement Explicite" : "التعليم الصريح";
            const tag2 = isFr ? "École Pionnière" : "المدرسة الرائدة";
            const seanceBadge = d.seance_ncm_badge || (isFr ? `Séance (NCM ${d.ncm_number || ncmNum})` : `خطاطة رقم (${d.ncm_number || ncmNum})`);
            return `<div class="center-hub-box"><div id="centralHub" class="center-blue-circle" style="padding: 16px 12px; gap: 2px;"><div class="text-[10px] font-extrabold text-amber-300 leading-tight">${tag1}</div><div class="text-[10px] font-bold text-white opacity-95 leading-tight mb-0.5">${tag2}</div><div contenteditable="true" class="text-[11.5px] font-black text-white bg-white/20 py-0.5 px-2.5 rounded-full border border-white/30 shadow-inner leading-tight max-w-[92%]">${d.subject_level || ''}</div><div contenteditable="true" class="text-[10px] font-bold text-slate-100 leading-tight mt-0.5">${d.unit_week || ''}</div><div contenteditable="true" class="text-[10.5px] font-black text-amber-300 bg-amber-500/25 border border-amber-300/40 px-2.5 py-0.5 rounded-full leading-tight mt-0.5">${seanceBadge}</div>${d.livret_pages ? `<div contenteditable="true" class="text-[9.5px] font-semibold text-cyan-200 bg-black/30 py-0.5 px-2 rounded-full leading-tight mt-0.5">${d.livret_pages}</div>` : ''}</div></div>`;
        }

        function drawConnectors() {
            const container = document.getElementById('mindmapContainer');
            const svg = document.getElementById('pathSvg');
            const hub = document.getElementById('centralHub');
            const colCenter = document.getElementById('colCenter');
            if (!container || !svg || !hub || !colCenter) return;
            const cRect = container.getBoundingClientRect();
            if (cRect.width === 0) return;
            svg.setAttribute('viewBox', `0 0 ${cRect.width} ${cRect.height}`);
            svg.innerHTML = '';

            const hubRect = hub.getBoundingClientRect();
            const centerColRect = colCenter.getBoundingClientRect();
            const hx = hubRect.left - cRect.left + hubRect.width / 2;
            const hy = hubRect.top - cRect.top + hubRect.height / 2;
            const radius = hubRect.width / 2;

            container.querySelectorAll('.station-box').forEach((card, i) => {
                const idx = parseInt(card.getAttribute('data-st-idx') || i, 10);
                const color = stationColors[idx % stationColors.length];
                const cardRect = card.getBoundingClientRect();
                const cx = cardRect.left - cRect.left + cardRect.width / 2;
                const cy = cardRect.top - cRect.top + cardRect.height / 2;

                let startX, startY, targetX, targetY, dPath;
                const isLeftCol = cx < hx - 70;
                const isRightCol = cx > hx + 70;

                if (!isLeftCol && !isRightCol) {
                    // محطة العمود الأوسط (أسفل أو أعلى الدائرة مباشرة)
                    targetX = cx;
                    if (cy > hy) {
                        startX = hx;
                        startY = hy + radius + 3;
                        targetY = cardRect.top - cRect.top - 3;
                    } else {
                        startX = hx;
                        startY = hy - radius - 3;
                        targetY = cardRect.bottom - cRect.top + 3;
                    }
                    dPath = `M ${startX} ${startY} L ${targetX} ${targetY}`;
                } else {
                    // تحديد نقطة الاتصال على حافة البطاقة والممر الفاصل بين الأعمدة
                    targetY = cy;
                    const isLowerCard = cy > hy + 45;
                    const isUpperCard = cy < hy - 45;
                    const angle = isLowerCard ? (Math.PI / 7) : (isUpperCard ? (-Math.PI / 9) : 0);

                    if (isRightCol) {
                        startX = hx + Math.cos(angle) * (radius + 3);
                        startY = hy + Math.sin(angle) * (radius + 3);
                        targetX = cardRect.left - cRect.left - 3;
                        const gapLeft = centerColRect.right - cRect.left;
                        const corridorX = isLowerCard ? (gapLeft + (targetX - gapLeft) * 0.42) : (gapLeft + (targetX - gapLeft) * 0.68);
                        const r = 12;
                        if (Math.abs(targetY - startY) < 28) {
                            dPath = `M ${startX} ${startY} C ${corridorX} ${startY}, ${corridorX} ${targetY}, ${targetX} ${targetY}`;
                        } else {
                            const dirY = targetY > startY ? 1 : -1;
                            dPath = `M ${startX} ${startY} L ${corridorX - r} ${startY} Q ${corridorX} ${startY} ${corridorX} ${startY + dirY * r} L ${corridorX} ${targetY - dirY * r} Q ${corridorX} ${targetY} ${corridorX + r} ${targetY} L ${targetX} ${targetY}`;
                        }
                    } else {
                        startX = hx - Math.cos(angle) * (radius + 3);
                        startY = hy + Math.sin(angle) * (radius + 3);
                        targetX = cardRect.right - cRect.left + 3;
                        const gapRight = centerColRect.left - cRect.left;
                        const corridorX = isLowerCard ? (gapRight - (gapRight - targetX) * 0.42) : (gapRight - (gapRight - targetX) * 0.68);
                        const r = 12;
                        if (Math.abs(targetY - startY) < 28) {
                            dPath = `M ${startX} ${startY} C ${corridorX} ${startY}, ${corridorX} ${targetY}, ${targetX} ${targetY}`;
                        } else {
                            const dirY = targetY > startY ? 1 : -1;
                            dPath = `M ${startX} ${startY} L ${corridorX + r} ${startY} Q ${corridorX} ${startY} ${corridorX} ${startY + dirY * r} L ${corridorX} ${targetY - dirY * r} Q ${corridorX} ${targetY} ${corridorX - r} ${targetY} L ${targetX} ${targetY}`;
                        }
                    }
                }

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', dPath);
                path.setAttribute('stroke', color);
                path.setAttribute('stroke-width', '2.6');
                path.setAttribute('stroke-dasharray', '6,4');
                path.setAttribute('stroke-linecap', 'round');
                path.setAttribute('fill', 'none');
                svg.appendChild(path);

                const startDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                startDot.setAttribute('cx', startX);
                startDot.setAttribute('cy', startY);
                startDot.setAttribute('r', '3.8');
                startDot.setAttribute('fill', '#ffffff');
                startDot.setAttribute('stroke', color);
                startDot.setAttribute('stroke-width', '2.4');
                svg.appendChild(startDot);

                const endDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                endDot.setAttribute('cx', targetX);
                endDot.setAttribute('cy', targetY);
                endDot.setAttribute('r', '4.5');
                endDot.setAttribute('fill', color);
                endDot.setAttribute('stroke', '#ffffff');
                endDot.setAttribute('stroke-width', '1.6');
                svg.appendChild(endDot);
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

            const rawStations = d.stations || [];
            const stations = stationsCount > 0 ? rawStations.slice(0, stationsCount) : rawStations.slice(0, 6);
            const colFirst = document.getElementById('colFirst');
            const colCenter = document.getElementById('colCenter');
            const colLast = document.getElementById('colLast');
            colFirst.innerHTML = ''; colCenter.innerHTML = ''; colLast.innerHTML = '';
            colCenter.classList.remove('only-hub');
            const hubHtml = createCenterHub(d, isFr, d.ncm_number || ncmNum);

            if (stations.length === 2) {
                colCenter.classList.add('only-hub');
                colFirst.innerHTML = createStationCard(stations[0], 0, isFr);
                colCenter.innerHTML = hubHtml;
                colLast.innerHTML = createStationCard(stations[1], 1, isFr);
            } else if (stations.length === 3) {
                colCenter.classList.add('only-hub');
                colFirst.innerHTML = createStationCard(stations[0], 0, isFr) + createStationCard(stations[1], 1, isFr);
                colCenter.innerHTML = hubHtml;
                colLast.innerHTML = createStationCard(stations[2], 2, isFr);
            } else if (stations.length === 4) {
                colCenter.classList.add('only-hub');
                colFirst.innerHTML = createStationCard(stations[0], 0, isFr) + createStationCard(stations[1], 1, isFr);
                colCenter.innerHTML = hubHtml;
                colLast.innerHTML = createStationCard(stations[2], 2, isFr) + createStationCard(stations[3], 3, isFr);
            } else if (stations.length === 5) {
                colFirst.innerHTML = createStationCard(stations[0], 0, isFr) + createStationCard(stations[1], 1, isFr);
                colCenter.innerHTML = hubHtml + createStationCard(stations[2], 2, isFr);
                colLast.innerHTML = createStationCard(stations[3], 3, isFr) + createStationCard(stations[4], 4, isFr);
            } else if (stations.length >= 6) {
                // في 6 محطات: 3 يميناً و3 يساراً والدائرة حرة في المنتصف لضمان عدم تداخل أي خط
                colCenter.classList.add('only-hub');
                colFirst.innerHTML = createStationCard(stations[0], 0, isFr) + createStationCard(stations[1], 1, isFr) + createStationCard(stations[2], 2, isFr);
                colCenter.innerHTML = hubHtml;
                colLast.innerHTML = createStationCard(stations[3], 3, isFr) + createStationCard(stations[4], 4, isFr) + createStationCard(stations[5], 5, isFr);
            }

            document.getElementById('printBar').classList.remove('hidden');
            document.getElementById('sheetWrapper').classList.remove('hidden');
            setTimeout(() => {
                fitNcmToSinglePage();
                document.getElementById('sheetWrapper').scrollIntoView({ behavior: 'smooth' });
            }, 100);
        }

        async function runSmartTool(toolType) {
            const text = document.getElementById(toolType + 'Input').value.trim();
            const fileObj = toolFiles[toolType] || {};
            const apiKey = localStorage.getItem('gemini_api_key');
            if (!text && !fileObj.b64) return alert('يرجى إدخال النص أو رفع ملف/صورة أولاً.');
            const btn = document.getElementById(toolType + 'Btn');
            const origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ جاري إعداد الإجابة...</span>';

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
            alert('تم نسخ المحتوى بنجاح.');
        }
        window.addEventListener('resize', fitNcmToSinglePage);
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
    stations = int(data.get('stations', 0))
    ncm_num = (data.get('ncm_num') or '').strip()
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
    if not overrides.get('ncm') and fn_meta.get('ncm'):
        ncm_num = fn_meta.get('ncm')

    is_fr = filename.upper().startswith('FR') or (text and len(re.findall(r'[a-zA-Zéèêëàâîïôùûç]', text[:2500])) > len(re.findall(r'[\u0600-\u06FF]', text[:2500])))

    if is_fr:
        station_rule = (
            f"Divise la séance en EXACTEMENT {stations} stations méthodologiques correspondant aux étapes clés du cours."
            if stations > 0 else
            "Détecte et extrais EXACTEMENT toutes les étapes/stations réelles présentes dans le support de cours (entre 4 et 6 stations : ex. Ouverture / Activités rituelles, Mise en situation / Modelage, Pratique guidée, Pratique autonome, Clôture)."
        )
        system_prompt = f"""Tu es un inspecteur pédagogique expert de l'Enseignement Explicite (École Pionnière au Maroc).
Analyse minutieusement le contenu du cours ci-joint et conçois une fiche méthodologique complète qui tient sur UNE SEULE page A4 paysage :
1. RÈGLE DE LANGUE : Réponds 100% en FRANÇAIS ("lang": "fr"). Zéro mot en arabe.
2. MÉTADONNÉES EXACTES (Niveau={lvl}, Période={per}, Unité={uni}, Semaine={sem}, Séance={sea}) :
   - header_title : "[Matière uniquement, ex: Français ou Mathématiques, SANS sous-composantes entre parenthèses] – Niveau {lvl or '...'} | Période {per or '...'} - Unité {uni or '...'} - Semaine {sem or '...'} - Séance {sea or '...'}"
   - lesson_subtitle : "Enseignement explicite | [Titre exact de la leçon] (Livret : p. [numéro exact de page si mentionné])"
   - objectives : Les objectifs d'apprentissage exacts formulés de manière concise.
3. STATIONS, CONTENU PÉDAGOGIQUE RICHE ET DURÉES RÉELLES :
   - {station_rule}
   - RÈGLE STRICTE SUR LES DURÉES : La durée de chaque station DOIT être un nombre réaliste compris entre **5 min et 40 min** (ex: "5 min", "10 min", "15 min", "20 min"). N'écris JAMAIS des nombres aberrants comme 100 min ou 150 min !
   - CONTENU DE CHAQUE STATION : Rédige exactement **3 puces pédagogiques riches, équilibrées et précises** ("label" : "text", 14 à 22 mots par puce) contenant les sous-étapes exactes, les exemples concrets du support (mots, phrases, calculs, pages du livret), le rôle de l'enseignant et la tâche des élèves.
Retourne UNIQUEMENT un objet JSON valide :
{{"lang":"fr","ncm_number":"{ncm_num or 'numéro déduit de la séance'}","header_title":"...","lesson_subtitle":"...","objectives":"...","subject_level":"...","unit_week":"Période ... - Unité ... | Semaine ...","seance_ncm_badge":"Séance ... (NCM {ncm_num})","livret_pages":"Livret : p. ...","stations":[{{"title":"...","duration":"15 min","bullets":[{{"label":"...","text":"..."}}]}}]}}"""
    else:
        station_rule = (
            f"قسّم الحصة إلى ({stations}) محطات منهجية بالضبط تغطي كافة مراحل الدرس."
            if stations > 0 else
            "استخرج بدقة جميع المحطات والمراحل الفعلية الواردة في ملف الدرس (بين 4 إلى 6 محطات حسب بنية الحصة في المدرسة الرائدة)."
        )
        system_prompt = f"""أنت مفتش وخبير بيداغوجي في برنامج التعليم الصريح بالمدرسة الرائدة بالمغرب.
حلّل محتوى الدرس المرفق بدقة متناهية وصمّم خطاطة بيداغوجية احترافية مصممة لتتسع في **صفحة A4 أفقية واحدة** بتناسق بصري كامل:
1. قاعدة اللغة: رد باللغة العربية الفصحى 100% ("lang": "ar").
2. استخراج بيانات الترويسة الدقيقة من الملف (المستوى={lvl}، المرحلة={per}، الوحدة={uni}، الأسبوع={sem}، الحصة={sea}):
   - header_title: "[المادة والمكون] – المستوى {lvl or '...'} | المرحلة {per or '...'} - الوحدة {uni or '...'} - الأسبوع {sem or '...'} - الحصة {sea or '...'}"
   - lesson_subtitle: "برنامج التعليم الصريح | [العنوان الدقيق للدرس] (الكراسة: ص. [رقم الصفحة الدقيق])"
   - objectives: أهداف التعلم الدقيقة للحصة مصاغة بتركيز ووضوح.
3. المحطات، المضمون البيداغوجي المتناسق، والمدد الزمنية المضبوطة:
   - {station_rule}
   - قاعدة صارمة للمدد الزمنية: استخرج المدة الدقيقة لكل محطة كما وردت في شريحة تنظيم الحصة (مثلاً: أنشطة اعتيادية 10 د، معجم 20 د، استماع وتحدث 20 د، قراءة 40 د، خط ونقل 15 د، اختتام 5 د). انتبه من التصاق حرف «د» بالرقم، وتأكد أن كل مدة بين **5 د و 45 د فقط**.
   - المضمون البيداغوجي لكل محطة: اكتب داخل كل محطة **3 فقرات بيداغوجية متوازنة الطول وغنية بالمضمون** ("label": "text"، بحدود 15 إلى 24 كلمة للفقرة الواحدة) حتى تملأ المربع بتناسق تام، مع ذكر: الخطوات الفرعية الدقيقة (أو تفصيل مهام المستوى 1 والمستوى 2 في الأقسام المشتركة)، الكلمات البصرية والمفردات والحروف والأمثلة الفعلية المذكورة في الشرائح، وأرقام صفحات الكراسة.
أرجع JSON صالحاً فقط:
{{"lang":"ar","ncm_number":"{ncm_num or 'رقم الخطاطة المستنتج من الدرس'}","header_title":"...","lesson_subtitle":"...","objectives":"...","subject_level":"...","unit_week":"المرحلة ... – الوحدة ... | الأسبوع ...","seance_ncm_badge":"الحصة ... (خطاطة {ncm_num})","livret_pages":"الكراسة: ص. ...","stations":[{{"title":"...","duration":"15 د","bullets":[{{"label":"...","text":"..."}}]}}]}}"""

    parts = [{"text": system_prompt + "\n\nLesson Content:\n" + (text[:40000] if text else "Analyze the attached lesson file thoroughly.")}]
    if file_b64 and mime_type:
        parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    raw_text, err = call_gemini_api(api_key, parts, json_mode=True, temperature=0.05, high_rigor=True)
    if err or not raw_text:
        return jsonify({'error': f'تعذر التوليد: {err}'})
    try:
        res_json = json.loads(re.search(r'\{[\s\S]*\}', raw_text).group(0))
        res_json = sanitize_ncm_data(res_json)
        if stations > 0 and 'stations' in res_json:
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
        is_rigorous = False
    elif tool == 'summarizer':
        prompt = f"""You are an elite university professor and instructional designer.
{lang_rule}
Analyze the input thoroughly and produce an executive, deeply structured academic synthesis:
1. **الإطار العام والهدف المحوري / Vue d'ensemble** : Core thesis and scope of the document.
2. **المفاهيم والقواعد الأساسية / Concepts et règles clés** : Precise definitions, laws, or formulas (using LaTeX $...$ / $$...$$ if applicable).
3. **الهيكلة التفصيلية للمحاور / Synthèse structurée par axes** : Clear hierarchical breakdown of all sections.
4. **خلاصة تركيبية مركزة / Points essentiels à retenir** : High-yield takeaways in a structured table or callout block."""
        is_rigorous = False
    else:
        domain = options.get('domain', 'Mathematics & Sciences')
        depth = options.get('depth', 'deep')
        is_rigorous = True
        if depth == 'concise':
            depth_instruction = "Provide a direct, laser-focused solution showing every essential equation, exact algebraic transitions, and boxed final result."
        elif depth == 'pedagogical':
            depth_instruction = "Provide a pedagogical, learner-friendly breakdown explaining the intuition behind each step, why each theorem is chosen, and how to avoid common pitfalls."
        else:
            depth_instruction = r"""STRICT MATHEMATICAL & SCIENTIFIC RIGOR PROTOCOL (ZERO-ERROR TOLERANCE):
1. **ZERO HESITATION OR SELF-CORRECTION IN OUTPUT**: Never write internal monologue, doubts, or corrections in the text (e.g., NEVER write "Attention...", "Précisons...", "Attendez...", "Corrigeons..."). Verify the exact bounds of sums, indices, and hypotheses silently BEFORE writing the clean, definitive proof.
2. **ZERO HAND-WAVING OR SKIPPED STEPS**: It is strictly FORBIDDEN to skip proofs at the end of an exercise using phrases like "on vérifie facilement", "on obtient directement par Cauchy-Schwarz", or "par sous-additivité". You MUST write out every intermediate algebraic substitution, index shift, quantifier ($\forall, \exists$), and inequality step-by-step from start to finish.
   - When proving an inequality involving an $\inf$, explicitly state the test variables, sum the inequalities, and pass to the infimum rigorously.
   - When applying Cauchy-Schwarz or mathematical induction, write the explicit vectors/terms and the complete algebraic chain.
3. **MANDATORY STRUCTURE FOR EACH EXERCISE**:
   - **1. قراءة تحليلية للمعطيات والمطلوب / Cadre formel et objectif** : Exact definitions and hypotheses.
   - **2. التأصيل النظري والمبرهنات / Théorèmes et propriétés de référence** : Exact formulas used.
   - **3. الحل المفصل خطوة بخطوة / Résolution détaillée question par question** : Solve EVERY single question and sub-question (1, 2, 3, 4, 5, 6...) with 100% completeness, giving the last questions the exact same depth and detail as the first question. Use clean LaTeX ($...$ inline, $$...$$ display). Put final results of each question in a Markdown blockquote (`>`).
   - **4. خلاصة منهجية / Synthèse méthodologique** : Brief high-level insight."""

        prompt = f"""You are a Chair Professor of {domain} (Professeur de Chaire Supérieure CPGE MPSI/MP* & Jury d'Agrégation).
{lang_rule}
{depth_instruction}"""

    parts = [{"text": prompt + "\n\nInput Content:\n" + (text[:40000] if text else "Transcribe every symbol, index, and bound of the attached document with 100% accuracy and solve every question completely.")}]
    if file_b64 and mime_type:
        parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    raw_text, err = call_gemini_api(api_key, parts, json_mode=False, temperature=0.04 if is_rigorous else 0.12, high_rigor=is_rigorous)
    if err or not raw_text:
        return jsonify({'error': f'خطأ: {err}'})
    return jsonify({'result': raw_text})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
