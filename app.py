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
    <title>الأكاديمية الذكية Pro | الخطاطات، حل المسائل، الملخصات، والترجمة</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <!-- محرك MathJax 3 لرسم المعادلات والرموز الرياضية والفيزيائية باحترافية -->
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                processEscapes: true
            },
            options: {
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre']
            }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Cairo', sans-serif; background: #0b1120; color: #f8fafc; margin: 0; overflow-x: hidden; }
        .glass-panel { background: rgba(30, 41, 59, 0.85); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.08); }
        .nav-tab { transition: all 0.25s ease; }
        .nav-tab.active { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; border-color: #60a5fa; box-shadow: 0 4px 15px rgba(37, 99, 235, 0.35); }

        .sheet-scroll-viewport {
            width: 100%;
            overflow-x: auto;
            padding-bottom: 12px;
            display: flex;
            justify-content: center;
        }

        .ncm-sheet {
            background: #ffffff;
            color: #0f172a;
            border-radius: 14px;
            padding: 18px 22px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.55);
            width: 1120px;
            min-width: 1120px;
            max-width: 1120px;
            margin: 0 auto;
            position: relative;
            border: 1px solid #cbd5e1;
            box-sizing: border-box;
        }

        .ncm-top-banner {
            background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%);
            color: white;
            border-radius: 12px;
            padding: 12px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin-bottom: 10px;
            border-bottom: 4px solid #f59e0b;
        }
        .ncm-orange-badge {
            background: linear-gradient(180deg, #f97316 0%, #ea580c 100%);
            color: white;
            border-radius: 10px;
            padding: 6px 16px;
            text-align: center;
            min-width: 95px;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.25);
            border: 1.5px solid rgba(255,255,255,0.4);
            flex-shrink: 0;
        }
        .ncm-objectives-box {
            background: #f8fafc;
            border: 1.5px solid #cbd5e1;
            border-right: 6px solid #2563eb;
            border-radius: 10px;
            padding: 9px 16px;
            margin-bottom: 16px;
            font-size: 13px;
            line-height: 1.55;
        }
        [dir="ltr"] .ncm-objectives-box {
            border-right: 1.5px solid #cbd5e1;
            border-left: 6px solid #2563eb;
        }

        .mindmap-container {
            position: relative;
            z-index: 1;
            width: 100%;
            padding: 4px 0;
        }
        #pathSvg {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 1;
        }
        .ncm-grid-layout {
            position: relative;
            z-index: 2;
            display: grid;
            grid-template-columns: 1fr 250px 1fr;
            gap: 28px;
            align-items: center;
        }

        .station-box {
            background: #ffffff;
            border: 2px solid #cbd5e1;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
            display: flex;
            flex-direction: column;
            height: auto;
        }
        .station-header-bar {
            color: white;
            padding: 8px 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            font-weight: 800;
            font-size: 13.5px;
        }
        .station-time-tag {
            background: rgba(0, 0, 0, 0.28);
            color: white;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: 11.5px;
            font-weight: 800;
            border: 1px solid rgba(255,255,255,0.4);
            white-space: nowrap;
            flex-shrink: 0;
        }
        .station-content-body {
            padding: 11px 14px;
            font-size: 12.5px;
            line-height: 1.65;
        }

        .center-hub-box {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 6px;
        }
        .center-blue-circle {
            width: 224px;
            height: 224px;
            border-radius: 50%;
            background: radial-gradient(circle at 35% 30%, #2563eb 0%, #1e3a8a 90%);
            color: white;
            padding: 15px;
            text-align: center;
            border: 5px solid #ffffff;
            outline: 3px solid #2563eb;
            box-shadow: 0 10px 28px rgba(37, 99, 235, 0.35);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            position: relative;
            margin: 0 auto;
        }

        [contenteditable="true"]:focus {
            outline: 2px dashed #f59e0b;
            background: rgba(245, 158, 11, 0.1);
            border-radius: 4px;
        }

        /* تنسيق مخرجات حل المسائل والملخصات والترجمة مع دعم كامل للفرنسية والعربية */
        .prose-output { line-height: 1.85; font-size: 15px; }
        .prose-output[dir="ltr"] { text-align: left; font-family: system-ui, -apple-system, 'Segoe UI', Roboto, 'Cairo', sans-serif; }
        .prose-output[dir="rtl"] { text-align: right; font-family: 'Cairo', sans-serif; }
        .prose-output h1, .prose-output h2, .prose-output h3 { color: #38bdf8; font-weight: 800; margin-top: 1.25rem; margin-bottom: 0.6rem; border-bottom: 1px solid rgba(56, 189, 248, 0.2); padding-bottom: 4px; }
        .prose-output p { margin-bottom: 0.85rem; }
        .prose-output ul, .prose-output ol { margin-bottom: 1rem; padding-inline-start: 1.5rem; }
        .prose-output ul { list-style-type: disc; }
        .prose-output ol { list-style-type: decimal; }
        .prose-output table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
        .prose-output th, .prose-output td { border: 1px solid #334155; padding: 8px 12px; }
        .prose-output th { background: #1e293b; color: #38bdf8; }
        .prose-output strong { color: #fcd34d; font-weight: 800; }
        .prose-output hr { border-color: #334155; margin: 1.2rem 0; }
        mjx-container { overflow-x: auto; overflow-y: hidden; max-width: 100%; padding: 2px 0; }

        @media print {
            @page { size: A4 landscape; margin: 4mm; }
            html, body {
                background: white !important;
                color: black !important;
                margin: 0 !important;
                padding: 0 !important;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }
            .no-print { display: none !important; }
            .sheet-scroll-viewport { overflow: visible !important; padding: 0 !important; display: block !important; }
            .ncm-sheet {
                box-shadow: none !important;
                border: none !important;
                width: 100% !important;
                min-width: 100% !important;
                max-width: 100% !important;
                padding: 2mm 4mm !important;
                margin: 0 !important;
                page-break-inside: avoid !important;
            }
            .ncm-grid-layout {
                grid-template-columns: 1fr 225px 1fr !important;
                gap: 22px !important;
            }
            .center-blue-circle { width: 205px !important; height: 205px !important; }
            .prose-print-box { background: white !important; color: #0f172a !important; border: none !important; box-shadow: none !important; }
            .prose-output, .prose-output p, .prose-output li, .prose-output td { color: #0f172a !important; }
            .prose-output h1, .prose-output h2, .prose-output h3 { color: #1e3a8a !important; border-color: #cbd5e1 !important; }
            .prose-output strong { color: #b45309 !important; }
        }
    </style>
</head>
<body class="p-3 md:p-6">
    <!-- شريط التنقل العلوي -->
    <div class="max-w-6xl mx-auto no-print">
        <header class="flex flex-wrap items-center justify-between gap-4 mb-5 glass-panel p-4 rounded-2xl">
            <div class="flex items-center gap-3">
                <div class="w-11 h-11 rounded-xl bg-gradient-to-tr from-blue-600 to-cyan-500 flex items-center justify-center shadow-lg">
                    <span class="text-xl">🎓</span>
                </div>
                <div>
                    <h1 class="text-lg md:text-xl font-black text-white">المنصة التربوية والعلمية الذكية <span class="text-cyan-400">Pro</span></h1>
                    <p class="text-xs text-slate-400 font-semibold">الخطاطات الرسمية • حل المسائل المعقدة • التلخيص الذكي • الترجمة الأكاديمية</p>
                </div>
            </div>

            <div class="flex flex-wrap items-center gap-2">
                <button onclick="switchSection('ncm', this)" class="nav-tab active px-3.5 py-2 rounded-xl border border-slate-700 bg-slate-800/80 text-xs font-extrabold flex items-center gap-1.5">
                    <span>🗺️</span> خطاطات الرائدة (NCM)
                </button>
                <button onclick="switchSection('solver', this)" class="nav-tab px-3.5 py-2 rounded-xl border border-slate-700 bg-slate-800/80 text-xs font-extrabold text-slate-300 flex items-center gap-1.5">
                    <span>🧮</span> حلّال المسائل المعقدة
                </button>
                <button onclick="switchSection('summarizer', this)" class="nav-tab px-3.5 py-2 rounded-xl border border-slate-700 bg-slate-800/80 text-xs font-extrabold text-slate-300 flex items-center gap-1.5">
                    <span>📑</span> الملخص الذكي
                </button>
                <button onclick="switchSection('translator', this)" class="nav-tab px-3.5 py-2 rounded-xl border border-slate-700 bg-slate-800/80 text-xs font-extrabold text-slate-300 flex items-center gap-1.5">
                    <span>🌐</span> الترجمة الدقيقة
                </button>
                <button onclick="toggleApiModal()" title="إعدادات الاتصال" class="p-2 rounded-xl bg-slate-800/60 hover:bg-slate-700 border border-slate-700 text-xs text-slate-400">
                    ⚙️
                </button>
            </div>
        </header>

        <!-- نافذة إعداد المفتاح -->
        <div id="apiModal" class="hidden fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
            <div class="glass-panel p-6 rounded-3xl max-w-md w-full border border-blue-500/40">
                <h3 class="text-base font-bold mb-2 text-cyan-400">إعداد مفتاح الخدمة السحابية</h3>
                <p class="text-xs text-slate-400 mb-3">أدخل مفتاح API لتفعيل المعالجة الذكية على متصفحك:</p>
                <input type="password" id="apiKeyInput" placeholder="أدخل المفتاح هنا..." class="w-full p-3 rounded-xl bg-slate-900 border border-slate-700 text-white mb-4 text-left font-mono text-sm" dir="ltr">
                <div class="flex justify-end gap-2">
                    <button onclick="toggleApiModal()" class="px-4 py-2 rounded-xl bg-slate-800 text-xs font-bold">إغلاق</button>
                    <button onclick="saveApiKey()" class="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-black text-xs">حفظ التفعيل</button>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== القسم 1: مولد خطاطات المدرسة الرائدة ==================== -->
    <div id="sec-ncm" class="app-section max-w-6xl mx-auto">
        <div class="glass-panel rounded-3xl p-5 shadow-2xl mb-6 no-print">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                <div class="lg:col-span-2">
                    <label class="block text-xs font-bold text-cyan-400 mb-2">1. ارفع ملف الدرس (PPTX أو PDF أو صورة) أو الصق محتواه:</label>
                    <div class="flex gap-2 mb-2.5">
                        <label class="flex-1 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-cyan-500/50 rounded-2xl p-3 text-center transition flex items-center justify-center gap-2">
                            <span class="text-lg">📂</span>
                            <span id="ncmFileName" class="text-xs font-bold text-slate-200">اختر ملف الدرس (.pptx / .pdf / صورة) لاستخراج البيانات تلقائياً</span>
                            <input type="file" id="ncmFileInput" accept=".pptx,.ppt,.pdf,image/*,.txt" class="hidden" onchange="handleNcmFile(this)">
                        </label>
                        <button id="ncmClearBtn" onclick="clearNcmFile()" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="ncmTextInput" rows="3" placeholder="أو الصق نص الدرس أو الجذاذة هنا..." class="w-full p-3 rounded-2xl bg-slate-900/90 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400 text-xs"></textarea>
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

                        <label class="block text-[11px] font-bold text-slate-400 mb-1.5">بيانات الترويسة (تُستخرج تلقائياً ويمكنك تثبيتها):</label>
                        <div class="grid grid-cols-3 gap-1.5 mb-2">
                            <input id="metaLevel" type="text" placeholder="المستوى (تلقائي)" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaPeriode" type="text" placeholder="المرحلة (تلقائي)" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaUnite" type="text" placeholder="الوحدة (تلقائي)" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                        </div>
                        <div class="grid grid-cols-3 gap-1.5">
                            <input id="metaSemaine" type="text" placeholder="الأسبوع (تلقائي)" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="metaSeance" type="text" placeholder="الحصة (تلقائي)" class="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-center text-[11px] text-white">
                            <input id="ncmNumInput" type="text" placeholder="رقم الخطاطة" value="10" class="p-1.5 rounded-lg bg-slate-800 border border-amber-500/50 text-center font-black text-[11px] text-amber-300">
                        </div>
                    </div>
                </div>
            </div>

            <button onclick="generateNCM()" id="ncmGenBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-blue-600 via-indigo-600 to-cyan-600 hover:opacity-95 font-black text-white shadow-lg flex items-center justify-center gap-2 text-sm transition">
                <span id="ncmBtnText">توليد الخطاطة الرسمية بالترويسة الكاملة ⚡</span>
            </button>
        </div>

        <div id="printBar" class="hidden mb-3 flex flex-wrap items-center justify-between gap-2 glass-panel px-4 py-2.5 rounded-2xl no-print">
            <span class="text-xs font-bold text-emerald-400">✅ الخطاطة جاهزة (يمكنك النقر على أي نص لتعديله مباشرة قبل الطباعة)</span>
            <button onclick="window.print()" class="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-xs font-black text-white shadow-lg flex items-center gap-1.5">
                <span>🖨️ حفظ PDF / طباعة (A4 Paysage)</span>
            </button>
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

    <!-- ==================== القسم 2: حلال المسائل المعقدة ==================== -->
    <div id="sec-solver" class="app-section hidden max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <h2 class="text-base md:text-lg font-black text-cyan-400 mb-1">🧮 حلّال المسائل والتمارين المستعصية (بنفس لغة التمرين المرفوع)</h2>
            <p class="text-xs text-slate-400 mb-4">ارفع صورة التمرين أو ملف المسألة (PDF / صورة) أو اكتبها للحصول على الحل المفصل خطوة بخطوة مع رسم المعادلات الرياضية والفيزيائية بدقة.</p>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div class="md:col-span-2">
                    <div class="flex gap-2 mb-3">
                        <label class="flex-1 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-cyan-500/40 rounded-2xl p-3 text-center transition flex items-center justify-center gap-2">
                            <span>📷</span>
                            <span id="solverFileName" class="text-xs font-bold text-slate-200">ارفع صورة المسألة / التمرين أو ملف (PDF / PPTX)</span>
                            <input type="file" id="solverFileInput" accept="image/*,.pdf,.pptx,.txt" class="hidden" onchange="handleToolFile(this, 'solver')">
                        </label>
                        <button id="solverClearBtn" onclick="clearToolFile('solver')" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="solverInput" rows="4" placeholder="أو اكتب نص المسألة أو السؤال هنا (بأي لغة)..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:outline-none focus:border-cyan-400"></textarea>
                </div>
                <div class="bg-slate-900/70 p-4 rounded-2xl border border-slate-800 flex flex-col justify-between">
                    <div>
                        <label class="block text-xs font-bold text-cyan-400 mb-1.5">التخصص العلمي:</label>
                        <select id="solverDomain" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-2.5">
                            <option value="math">📐 الرياضيات (Mathématiques)</option>
                            <option value="physics">⚡ الفيزياء والكيمياء (Physique-Chimie)</option>
                            <option value="science">🧬 العلوم (SVT / Sciences)</option>
                            <option value="languages">📖 اللغات والقواعد (Langues & Grammaire)</option>
                        </select>
                        <label class="block text-xs font-bold text-cyan-400 mb-1.5">مستوى التفصيل:</label>
                        <select id="solverDetail" class="w-full p-2 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-2.5">
                            <option value="detailed">حل مفصل خطوة بخطوة مع البرهان (Détaillé)</option>
                            <option value="concise">حل مباشر ومختصر (Concis)</option>
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
            <button onclick="runSmartTool('solver')" id="solverBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-cyan-600 to-blue-600 font-black text-white text-sm shadow-lg">
                حل المسألة بدقة متناهية 🚀
            </button>
        </div>
        <div id="solverResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-bold text-emerald-400">✅ الحل العلمي المفصل</span>
                <div class="flex gap-2">
                    <button onclick="copyText('solverOutput')" class="px-3 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button onclick="window.print()" class="px-3 py-1.5 rounded-xl bg-blue-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
                </div>
            </div>
            <div id="solverOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 3: الملخص الذكي للملفات ==================== -->
    <div id="sec-summarizer" class="app-section hidden max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <h2 class="text-base md:text-lg font-black text-amber-400 mb-1">📑 الملخص الذكي للملفات والدروس والوثائق</h2>
            <p class="text-xs text-slate-400 mb-4">ارفع أي ملف (PDF، عرض PowerPoint، صورة وثيقة، أو نص طويل) لتحويله إلى ملخص احترافي مهيكل بنفس لغة الملف.</p>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div class="md:col-span-2">
                    <div class="flex gap-2 mb-3">
                        <label class="flex-1 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-amber-500/40 rounded-2xl p-3 text-center transition flex items-center justify-center gap-2">
                            <span>📄</span>
                            <span id="summarizerFileName" class="text-xs font-bold text-slate-200">ارفع الملف المراد تلخيصه (.pdf / .pptx / صورة)</span>
                            <input type="file" id="summarizerFileInput" accept=".pdf,.pptx,image/*,.txt" class="hidden" onchange="handleToolFile(this, 'summarizer')">
                        </label>
                        <button id="summarizerClearBtn" onclick="clearToolFile('summarizer')" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="summarizerInput" rows="4" placeholder="أو الصق النص الطويل هنا لتلخيصه..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:outline-none focus:border-amber-400"></textarea>
                </div>
                <div class="bg-slate-900/70 p-4 rounded-2xl border border-slate-800">
                    <label class="block text-xs font-bold text-amber-400 mb-2">أسلوب التلخيص:</label>
                    <select id="summarizerStyle" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-3">
                        <option value="structured">ملخص هيكلي شامل (محاور، نقاط، وجداول)</option>
                        <option value="rules">استخراج القواعد الأساسية والمفاهيم والتعاريف</option>
                        <option value="qa">أسئلة وأجوبة للمراجعة السريعة (Q&A)</option>
                    </select>
                    <label class="block text-xs font-bold text-amber-400 mb-2">لغة الملخص:</label>
                    <select id="summarizerLang" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="auto">تلقائي (نفس لغة الملف الأصلي 100%)</option>
                        <option value="fr">Français (100%)</option>
                        <option value="ar">العربية (100%)</option>
                        <option value="en">English (100%)</option>
                    </select>
                </div>
            </div>
            <button onclick="runSmartTool('summarizer')" id="summarizerBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-amber-500 to-orange-600 font-black text-slate-950 text-sm shadow-lg">
                توليد الملخص الاحترافي الآن ✨
            </button>
        </div>
        <div id="summarizerResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-bold text-amber-400">✅ الملخص المهيكل</span>
                <div class="flex gap-2">
                    <button onclick="copyText('summarizerOutput')" class="px-3 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button onclick="window.print()" class="px-3 py-1.5 rounded-xl bg-amber-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
                </div>
            </div>
            <div id="summarizerOutput" class="prose-output"></div>
        </div>
    </div>

    <!-- ==================== القسم 4: المترجم الاحترافي الدقيق ==================== -->
    <div id="sec-translator" class="app-section hidden max-w-5xl mx-auto">
        <div class="glass-panel rounded-3xl p-6 shadow-2xl mb-6 no-print">
            <h2 class="text-base md:text-lg font-black text-emerald-400 mb-1">🌐 المترجم الأكاديمي والتربوي الدقيق لكل اللغات</h2>
            <p class="text-xs text-slate-400 mb-4">ترجمة احترافية تحافظ على السياق والمصطلحات البيداغوجية والعلمية والمعادلات للنصوص والملفات المرفوعة.</p>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div class="md:col-span-2">
                    <div class="flex gap-2 mb-3">
                        <label class="flex-1 cursor-pointer bg-slate-800/90 hover:bg-slate-800 border-2 border-dashed border-emerald-500/40 rounded-2xl p-3 text-center transition flex items-center justify-center gap-2">
                            <span>🌍</span>
                            <span id="translatorFileName" class="text-xs font-bold text-slate-200">ارفع ملفاً أو صورة لترجمة محتواها (.pdf / .pptx / صورة)</span>
                            <input type="file" id="translatorFileInput" accept=".pdf,.pptx,image/*,.txt" class="hidden" onchange="handleToolFile(this, 'translator')">
                        </label>
                        <button id="translatorClearBtn" onclick="clearToolFile('translator')" class="hidden px-3 rounded-2xl bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-bold">حذف</button>
                    </div>
                    <textarea id="translatorInput" rows="4" placeholder="أو اكتب النص المراد ترجمته هنا..." class="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-700 text-white text-xs focus:outline-none focus:border-emerald-400"></textarea>
                </div>
                <div class="bg-slate-900/70 p-4 rounded-2xl border border-slate-800">
                    <label class="block text-xs font-bold text-emerald-400 mb-2">الترجمة إلى لغة:</label>
                    <select id="translatorTarget" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white mb-3">
                        <option value="French (Français académique)">الفرنسية (Français)</option>
                        <option value="Modern Standard Arabic (العربية الفصحى)">العربية</option>
                        <option value="Academic English">الإنجليزية (English)</option>
                        <option value="Spanish (Español)">الإسبانية (Español)</option>
                        <option value="German (Deutsch)">الألمانية (Deutsch)</option>
                        <option value="Standard Amazigh">الأمازيغية</option>
                    </select>
                    <label class="block text-xs font-bold text-emerald-400 mb-2">مجال الترجمة:</label>
                    <select id="translatorTone" class="w-full p-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs font-bold text-white">
                        <option value="Academic, scientific, and pedagogical">تربوي وعلمي وأكاديمي</option>
                        <option value="Official and administrative">إداري ورسمي</option>
                        <option value="Professional and literary">أدبي وعام</option>
                    </select>
                </div>
            </div>
            <button onclick="runSmartTool('translator')" id="translatorBtn" class="w-full py-3.5 rounded-2xl bg-gradient-to-r from-emerald-600 to-teal-600 font-black text-white text-sm shadow-lg">
                ترجمة فورية دقيقة 🌐
            </button>
        </div>
        <div id="translatorResultBox" class="hidden glass-panel rounded-3xl p-6 prose-print-box">
            <div class="flex justify-between items-center border-b border-slate-700 pb-3 mb-4 no-print">
                <span class="text-xs font-bold text-emerald-400">✅ النص المترجم</span>
                <div class="flex gap-2">
                    <button onclick="copyText('translatorOutput')" class="px-3 py-1.5 rounded-xl bg-slate-800 text-xs font-bold">📋 نسخ</button>
                    <button onclick="window.print()" class="px-3 py-1.5 rounded-xl bg-emerald-600 text-xs font-bold text-white">🖨️ طباعة / PDF</button>
                </div>
            </div>
            <div id="translatorOutput" class="prose-output"></div>
        </div>
    </div>

    <script>
        let stationsCount = 4;
        let ncmBase64 = null, ncmMime = null, ncmUploadedFilename = '';
        let toolFiles = { solver: {}, summarizer: {}, translator: {} };

        document.getElementById('apiKeyInput').value = localStorage.getItem('gemini_api_key') || '';

        /* دالة ذكية لعرض النصوص مع حماية المعادلات الرياضية ورسمها بواسطة MathJax وضبط اتجاه اللغة تلقائياً */
        function renderFormattedOutput(elementId, rawMarkdown) {
            const el = document.getElementById(elementId);
            if (!el) return;

            // 1. حماية المعادلات الرياضية من التعديل بواسطة Marked.js
            const mathBlocks = [];
            let protectedText = (rawMarkdown || '')
                .replace(/\$\$[\s\S]*?\$\$/g, match => {
                    mathBlocks.push(match);
                    return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`;
                })
                .replace(/\\\[[\s\S]*?\\\]/g, match => {
                    mathBlocks.push(match);
                    return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`;
                })
                .replace(/\\\([\s\S]*?\\\)/g, match => {
                    mathBlocks.push(match);
                    return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`;
                })
                .replace(/\$([^\$\n]+?)\$/g, match => {
                    mathBlocks.push(match);
                    return `@@MATH_BLOCK_${mathBlocks.length - 1}@@`;
                });

            // 2. تحويل Markdown إلى HTML
            let html = marked.parse(protectedText);

            // 3. استرجاع المعادلات الرياضية
            html = html.replace(/@@MATH_BLOCK_(\d+)@@/g, (_, idx) => mathBlocks[parseInt(idx, 10)]);

            // 4. اكتشاف لغة النص الناتج لضبط الاتجاه (LTR للفرنسية/الإنجليزية و RTL للعربية)
            const textWithoutMath = rawMarkdown.replace(/\$\$[\s\S]*?\$\$|\$[^\$\n]+?\$/g, '');
            const arabicChars = (textWithoutMath.match(/[\u0600-\u06FF]/g) || []).length;
            const latinChars = (textWithoutMath.match(/[a-zA-ZéèêëàâîïôùûçÉÈÊËÀÂÎÏÔÙÛÇ]/g) || []).length;
            const isRtl = arabicChars > latinChars;

            el.setAttribute('dir', isRtl ? 'rtl' : 'ltr');
            el.innerHTML = html;

            // 5. تفعيل MathJax لرسم الرموز والمعادلات الرياضية بجمالية عالية
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

        function toggleApiModal() {
            document.getElementById('apiModal').classList.toggle('hidden');
        }

        function saveApiKey() {
            const k = document.getElementById('apiKeyInput').value.trim();
            localStorage.setItem('gemini_api_key', k);
            toggleApiModal();
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
                    const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
                    callback(dataUrl.split(',')[1], 'image/jpeg');
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        }

        async function handleNcmFile(input) {
            const file = input.files[0];
            if (!file) return;
            ncmUploadedFilename = file.name;
            document.getElementById('ncmFileName').innerText = "⏳ جاري تحليل الملف: " + file.name;
            document.getElementById('ncmClearBtn').classList.remove('hidden');

            const fn = file.name.toUpperCase();
            const lvl = fn.match(/(?:N|NIVEAU|AEP)[_-]?(\d)/) || fn.match(/(\d)AEP/);
            const per = fn.match(/P(\d)/);
            const uni = fn.match(/U(\d)/);
            const sem = fn.match(/SEM[_-]?(\d+)/) || fn.match(/W(\d+)/);
            const sea = fn.match(/_S(\d+)/) || fn.match(/SEANCE[_-]?(\d+)/);
            const ncm = fn.match(/NCM[_-]?(\d+)/);

            if (lvl) document.getElementById('metaLevel').value = lvl[1];
            if (per) document.getElementById('metaPeriode').value = per[1];
            if (uni) document.getElementById('metaUnite').value = uni[1];
            if (sem) document.getElementById('metaSemaine').value = sem[1];
            if (sea) document.getElementById('metaSeance').value = sea[1];
            if (ncm) document.getElementById('ncmNumInput').value = ncm[1];

            if (file.name.toLowerCase().endsWith('.pptx')) {
                const formData = new FormData();
                formData.append('file', file);
                try {
                    const res = await fetch('/extract_pptx', { method: 'POST', body: formData });
                    const data = await res.json();
                    if (data.text) {
                        document.getElementById('ncmTextInput').value = data.text;
                        document.getElementById('ncmFileName').innerText = "✅ تم استخراج شرائح الدرس: " + file.name;
                        ncmBase64 = null;
                    }
                } catch (e) {
                    alert('خطأ أثناء قراءة ملف البوربوينت');
                }
                return;
            }

            if (file.type === 'application/pdf') {
                const reader = new FileReader();
                reader.onload = e => {
                    ncmBase64 = e.target.result.split(',')[1];
                    ncmMime = 'application/pdf';
                    document.getElementById('ncmFileName').innerText = "✅ تم إرفاق ملف PDF: " + file.name;
                };
                reader.readAsDataURL(file);
            } else if (file.type.startsWith('image/')) {
                compressImageFile(file, (b64, mime) => {
                    ncmBase64 = b64;
                    ncmMime = mime;
                    document.getElementById('ncmFileName').innerText = "✅ تم إرفاق الصورة: " + file.name;
                });
            } else {
                const reader = new FileReader();
                reader.onload = e => {
                    document.getElementById('ncmTextInput').value = e.target.result;
                    ncmBase64 = null;
                    document.getElementById('ncmFileName').innerText = "✅ تم قراءة الملف: " + file.name;
                };
                reader.readAsText(file);
            }
        }

        function clearNcmFile() {
            document.getElementById('ncmFileInput').value = '';
            document.getElementById('ncmFileName').innerText = 'اختر ملف الدرس (.pptx / .pdf / صورة) لاستخراج البيانات تلقائياً';
            document.getElementById('ncmClearBtn').classList.add('hidden');
            ncmBase64 = null; ncmMime = null; ncmUploadedFilename = '';
        }

        async function handleToolFile(input, toolKey) {
            const file = input.files[0];
            if (!file) return;
            const labelEl = document.getElementById(toolKey + 'FileName');
            const clearBtn = document.getElementById(toolKey + 'ClearBtn');
            labelEl.innerText = "⏳ جاري قراءة المرفق: " + file.name;
            if (clearBtn) clearBtn.classList.remove('hidden');

            if (file.name.toLowerCase().endsWith('.pptx')) {
                const formData = new FormData();
                formData.append('file', file);
                const res = await fetch('/extract_pptx', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.text) {
                    document.getElementById(toolKey + 'Input').value = data.text;
                    toolFiles[toolKey] = { filename: file.name };
                    labelEl.innerText = "✅ تم استخراج محتوى العرض: " + file.name;
                }
            } else if (file.type === 'application/pdf') {
                const reader = new FileReader();
                reader.onload = e => {
                    toolFiles[toolKey] = { b64: e.target.result.split(',')[1], mime: 'application/pdf', filename: file.name };
                    labelEl.innerText = "✅ جاهز (PDF): " + file.name;
                };
                reader.readAsDataURL(file);
            } else if (file.type.startsWith('image/')) {
                compressImageFile(file, (b64, mime) => {
                    toolFiles[toolKey] = { b64: b64, mime: mime, filename: file.name };
                    labelEl.innerText = "✅ جاهز (صورة): " + file.name;
                });
            } else {
                const reader = new FileReader();
                reader.onload = e => {
                    document.getElementById(toolKey + 'Input').value = e.target.result;
                    toolFiles[toolKey] = { filename: file.name };
                    labelEl.innerText = "✅ تم قراءة النص: " + file.name;
                };
                reader.readAsText(file);
            }
        }

        function clearToolFile(toolKey) {
            const fileInput = document.getElementById(toolKey + 'FileInput');
            if (fileInput) fileInput.value = '';
            toolFiles[toolKey] = {};
            document.getElementById(toolKey + 'FileName').innerText = 'ارفع ملفاً أو صورة (.pdf / .pptx / صورة)';
            const clearBtn = document.getElementById(toolKey + 'ClearBtn');
            if (clearBtn) clearBtn.classList.add('hidden');
        }

        async function generateNCM() {
            const text = document.getElementById('ncmTextInput').value.trim();
            const ncmNum = document.getElementById('ncmNumInput').value.trim() || '10';
            const apiKey = localStorage.getItem('gemini_api_key');

            if (!text && !ncmBase64) {
                return alert('يرجى رفع ملف الدرس أو لصق محتواه أولاً.');
            }

            const btn = document.getElementById('ncmGenBtn');
            const btnText = document.getElementById('ncmBtnText');
            btn.disabled = true;
            btnText.innerText = '⏳ جاري تحليل الدرس وبناء الخطاطة الرسمية بدقة...';

            try {
                const res = await fetch('/generate_ncm', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        text: text,
                        filename: ncmUploadedFilename,
                        stations: stationsCount,
                        ncm_num: ncmNum,
                        meta_overrides: {
                            level: document.getElementById('metaLevel').value.trim(),
                            periode: document.getElementById('metaPeriode').value.trim(),
                            unite: document.getElementById('metaUnite').value.trim(),
                            semaine: document.getElementById('metaSemaine').value.trim(),
                            seance: document.getElementById('metaSeance').value.trim()
                        },
                        file_b64: ncmBase64,
                        mime_type: ncmMime,
                        api_key: apiKey
                    })
                });
                const data = await res.json();
                if (data.error) {
                    alert(data.error);
                    if (data.need_key) toggleApiModal();
                } else {
                    renderNCMSheet(data.result, ncmNum);
                }
            } catch (e) {
                alert('تعذر الاتصال بالخادم، يرجى المحاولة مرة أخرى.');
            } finally {
                btn.disabled = false;
                btnText.innerText = 'توليد الخطاطة الرسمية بالترويسة الكاملة ⚡';
            }
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

            return `
                <div class="station-box" style="border-top: 4px solid ${color};">
                    <div class="station-header-bar" style="background: ${color};">
                        <span contenteditable="true">${idx + 1}. ${cleanTitle}</span>
                        ${st.duration ? `<span contenteditable="true" class="station-time-tag">${st.duration}</span>` : ''}
                    </div>
                    <div class="station-content-body">
                        <ul class="list-none p-0 m-0">${bulletsHtml}</ul>
                    </div>
                </div>
            `;
        }

        function createCenterHub(d, isFr, ncmNum) {
            const tag1 = isFr ? "Enseignement Explicite" : "التعليم الصريح";
            const tag2 = isFr ? "École Pionnière" : "المدرسة الرائدة";
            const seanceBadge = d.seance_ncm_badge || (isFr ? `NCM ${d.ncm_number || ncmNum}` : `خطاطة رقم (${d.ncm_number || ncmNum})`);

            return `
                <div class="center-hub-box">
                    <div id="centralHub" class="center-blue-circle">
                        <div class="text-[11px] font-extrabold text-amber-300 tracking-wide mb-0.5">${tag1}</div>
                        <div class="text-[11px] font-bold text-white mb-1.5 opacity-95">${tag2}</div>
                        <div contenteditable="true" class="text-sm md:text-base font-black text-white bg-white/20 py-1 px-4 rounded-full mb-1.5 border border-white/30 shadow-inner">
                            ${d.subject_level || ''}
                        </div>
                        <div contenteditable="true" class="text-[11px] font-bold text-slate-100 mb-1.5 leading-tight">${d.unit_week || ''}</div>
                        <div contenteditable="true" class="text-xs font-black text-amber-300 bg-amber-500/25 border border-amber-300/40 px-3 py-0.5 rounded-full mb-1">
                            ${seanceBadge}
                        </div>
                        ${d.livret_pages ? `<div contenteditable="true" class="text-[10.5px] font-semibold text-cyan-200 bg-black/30 py-0.5 px-2.5 rounded-full">${d.livret_pages}</div>` : ''}
                    </div>
                </div>
            `;
        }

        function drawConnectors() {
            const container = document.getElementById('mindmapContainer');
            const svg = document.getElementById('pathSvg');
            const hub = document.getElementById('centralHub');
            if (!container || !svg || !hub) return;

            const cRect = container.getBoundingClientRect();
            if (cRect.width === 0 || cRect.height === 0) return;

            svg.setAttribute('viewBox', `0 0 ${cRect.width} ${cRect.height}`);
            svg.innerHTML = '';

            const hubRect = hub.getBoundingClientRect();
            const hx = hubRect.left - cRect.left + hubRect.width / 2;
            const hy = hubRect.top - cRect.top + hubRect.height / 2;
            const radius = hubRect.width / 2;

            const cards = container.querySelectorAll('.station-box');
            cards.forEach((card, i) => {
                const color = stationColors[i % stationColors.length];
                const cardRect = card.getBoundingClientRect();
                const cx = cardRect.left - cRect.left + cardRect.width / 2;
                const cy = cardRect.top - cRect.top + cardRect.height / 2;

                let targetX, targetY;
                if (cx < hx - 80) {
                    targetX = cardRect.right - cRect.left;
                    targetY = cy;
                } else if (cx > hx + 80) {
                    targetX = cardRect.left - cRect.left;
                    targetY = cy;
                } else {
                    targetX = cx;
                    targetY = cy < hy ? (cardRect.bottom - cRect.top) : (cardRect.top - cRect.top);
                }

                const angle = Math.atan2(targetY - hy, targetX - hx);
                const startX = hx + Math.cos(angle) * (radius + 2);
                const startY = hy + Math.sin(angle) * (radius + 2);

                const midX = (startX + targetX) / 2;
                const dPath = Math.abs(cx - hx) > 80
                    ? `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${targetY}, ${targetX} ${targetY}`
                    : `M ${startX} ${startY} L ${targetX} ${targetY}`;

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', dPath);
                path.setAttribute('stroke', color);
                path.setAttribute('stroke-width', '2.8');
                path.setAttribute('stroke-dasharray', '6,5');
                path.setAttribute('fill', 'none');
                svg.appendChild(path);

                const startDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                startDot.setAttribute('cx', startX);
                startDot.setAttribute('cy', startY);
                startDot.setAttribute('r', '4');
                startDot.setAttribute('fill', '#ffffff');
                startDot.setAttribute('stroke', color);
                startDot.setAttribute('stroke-width', '2.5');
                svg.appendChild(startDot);

                const endDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                endDot.setAttribute('cx', targetX);
                endDot.setAttribute('cy', targetY);
                endDot.setAttribute('r', '5.5');
                endDot.setAttribute('fill', color);
                endDot.setAttribute('stroke', '#ffffff');
                endDot.setAttribute('stroke-width', '2');
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

            const stations = (d.stations || []).slice(0, stationsCount);
            const colFirst = document.getElementById('colFirst');
            const colCenter = document.getElementById('colCenter');
            const colLast = document.getElementById('colLast');
            colFirst.innerHTML = '';
            colCenter.innerHTML = '';
            colLast.innerHTML = '';

            const hubHtml = createCenterHub(d, isFr, d.ncm_number || ncmNum);

            if (stations.length === 2) {
                colFirst.innerHTML = createStationCard(stations[0], 0);
                colCenter.innerHTML = hubHtml;
                colLast.innerHTML = createStationCard(stations[1], 1);
            } else if (stations.length === 3) {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1);
                colCenter.innerHTML = hubHtml;
                colLast.innerHTML = createStationCard(stations[2], 2);
            } else if (stations.length === 4) {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1);
                colCenter.innerHTML = hubHtml;
                colLast.innerHTML = createStationCard(stations[2], 2) + createStationCard(stations[3], 3);
            } else if (stations.length === 5) {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1);
                colCenter.innerHTML = hubHtml + createStationCard(stations[2], 2);
                colLast.innerHTML = createStationCard(stations[3], 3) + createStationCard(stations[4], 4);
            } else {
                colFirst.innerHTML = createStationCard(stations[0], 0) + createStationCard(stations[1], 1);
                colCenter.innerHTML = createStationCard(stations[2], 2) + hubHtml + createStationCard(stations[3], 3);
                colLast.innerHTML = createStationCard(stations[4], 4) + createStationCard(stations[5], 5);
            }

            document.getElementById('printBar').classList.remove('hidden');
            document.getElementById('sheetWrapper').classList.remove('hidden');

            setTimeout(() => {
                if (window.MathJax && window.MathJax.typesetPromise) {
                    window.MathJax.typesetPromise([sheet]).then(drawConnectors).catch(drawConnectors);
                } else {
                    drawConnectors();
                }
                document.getElementById('sheetWrapper').scrollIntoView({ behavior: 'smooth' });
            }, 120);
        }

        async function runSmartTool(toolType) {
            const text = document.getElementById(toolType + 'Input').value.trim();
            const fileObj = toolFiles[toolType] || {};
            const apiKey = localStorage.getItem('gemini_api_key');

            if (!text && !fileObj.b64) {
                return alert('يرجى إدخال النص أو رفع ملف أولاً.');
            }

            const btn = document.getElementById(toolType + 'Btn');
            const origText = btn.innerText;
            btn.disabled = true;
            btn.innerText = '⏳ جاري التحليل والمعالجة الدقيقة بنفس لغة الملف...';

            let extraOptions = {};
            if (toolType === 'solver') {
                extraOptions = {
                    domain: document.getElementById('solverDomain').value,
                    detail: document.getElementById('solverDetail').value,
                    lang: document.getElementById('solverLang').value
                };
            } else if (toolType === 'summarizer') {
                extraOptions = {
                    style: document.getElementById('summarizerStyle').value,
                    lang: document.getElementById('summarizerLang').value
                };
            } else if (toolType === 'translator') {
                extraOptions = {
                    target: document.getElementById('translatorTarget').value,
                    tone: document.getElementById('translatorTone').value
                };
            }

            try {
                const res = await fetch('/smart_tool', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        tool: toolType,
                        text: text,
                        options: extraOptions,
                        file_b64: fileObj.b64,
                        mime_type: fileObj.mime,
                        api_key: apiKey
                    })
                });
                const data = await res.json();
                if (data.error) {
                    alert(data.error);
                    if (data.need_key) toggleApiModal();
                } else {
                    document.getElementById(toolType + 'ResultBox').classList.remove('hidden');
                    renderFormattedOutput(toolType + 'Output', data.result);
                    document.getElementById(toolType + 'ResultBox').scrollIntoView({ behavior: 'smooth' });
                }
            } catch (e) {
                alert('حدث خطأ في الاتصال بالخادم.');
            } finally {
                btn.disabled = false;
                btn.innerText = origText;
            }
        }

        function copyText(elementId) {
            const txt = document.getElementById(elementId).innerText;
            navigator.clipboard.writeText(txt);
            alert('تم نسخ المحتوى بنجاح!');
        }

        window.addEventListener('resize', drawConnectors);
        window.addEventListener('beforeprint', () => setTimeout(drawConnectors, 40));
        document.addEventListener('input', e => {
            if (e.target.closest('#mindmapContainer')) drawConnectors();
        });
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
    file = request.files['file']
    extracted = extract_pptx_text(file.stream)
    if not extracted.strip():
        return jsonify({'error': 'لم يتم العثور على نصوص داخل ملف البوربوينت'})
    return jsonify({'text': extracted})

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
        return jsonify({'error': 'يرجى إدخال مفتاح API من أيقونة الإعدادات (⚙️) في الأعلى.', 'need_key': True})

    fn_meta = parse_filename_metadata(filename)
    lvl = overrides.get('level') or fn_meta.get('level') or ''
    per = overrides.get('periode') or fn_meta.get('periode') or ''
    uni = overrides.get('unite') or fn_meta.get('unite') or ''
    sem = overrides.get('semaine') or fn_meta.get('semaine') or ''
    sea = overrides.get('seance') or fn_meta.get('seance') or ''

    is_fr = False
    if filename.upper().startswith('FR'):
        is_fr = True
    elif text:
        latin_count = len(re.findall(r'[a-zA-Zéèêëàâîïôùûç]', text[:2000]))
        arab_count = len(re.findall(r'[\u0600-\u06FF]', text[:2000]))
        is_fr = latin_count > arab_count

    meta_hints = f"Metadata Hints -> Level: {lvl or 'extract from file'}, Période/المرحلة: {per or 'extract'}, Unité/الوحدة: {uni or 'extract'}, Semaine/الأسبوع: {sem or 'extract'}, Séance/الحصة: {sea or 'extract'}, NCM: {ncm_num}."

    if is_fr:
        system_prompt = f"""Tu es un expert pédagogique de l'Enseignement Explicite (École Pionnière au Maroc).
RÈGLE ABSOLUE DE LANGUE : Réponds 100% en FRANÇAIS uniquement ("lang": "fr"). N'écris AUCUN mot en arabe !
{meta_hints}

CONSIGNES STRICTES :
1. EN-TÊTE COMPLET OBLIGATOIRE ("header_title") :
   Format exact : "Français – Niveau [X] | Période [P] - Unité [U] - Semaine [W] - Séance [S]".
2. SOUS-TITRE ("lesson_subtitle") :
   Format exact : "Enseignement explicite | [Intitulé complet de la leçon] (Livret : p. [pages])"
3. CERCLE CENTRAL :
   - "subject_level": "Français N[X]"
   - "unit_week": "Période [P] - Unité [U] | Semaine [W]"
   - "seance_ncm_badge": "Séance [S] (NCM {ncm_num})"
4. DURÉES EXACTES DES STATIONS :
   Extrais la durée réelle en minutes de chaque étape depuis le document (ex: "10 min", "25 min", "20 min", "5 min").
5. NOMBRE DE STATIONS :
   Divise la séance en EXACTEMENT ({stations}) stations équilibrées.

Retourne UNIQUEMENT un objet JSON valide :
{{
  "lang": "fr",
  "ncm_number": "{ncm_num}",
  "header_title": "Français – Niveau ... | Période ... - Unité ... - Semaine ... - Séance ...",
  "lesson_subtitle": "Enseignement explicite | ... (Livret : p. ...)",
  "objectives": "Seuil de maîtrise ≥ 80% : ...",
  "subject_level": "Français N...",
  "unit_week": "Période ... - Unité ... | Semaine ...",
  "seance_ncm_badge": "Séance ... (NCM {ncm_num})",
  "livret_pages": "Livret : p. ...",
  "stations": [
    {{
      "title": "Titre de la station (sans numéro)",
      "duration": "ex: 20 min",
      "bullets": [
        {{
          "label": "Étape clé",
          "text": "Description précise des activités, exemples et consignes"
        }}
      ]
    }}
  ]
}}"""
    else:
        system_prompt = f"""أنت خبير بيداغوجي في برنامج التعليم الصريح بالمدرسة الرائدة المغربية.
قاعدة اللغة الصارمة: إذا كان الملف المرفوع بالفرنسية يجب أن ترد بالفرنسية 100% ("lang": "fr")، وإذا كان بالعربية فردّ بالعربية 100% ("lang": "ar").
{meta_hints}

ضوابط إلزامية دقيقة:
1. الترويسة العلوية الكاملة ("header_title"):
   "[المادة] – المستوى [X] | المرحلة [P] - الوحدة [U] - الأسبوع [W] - الحصة [S]"
2. العنوان الفرعي ("lesson_subtitle"):
   "برنامج التعليم الصريح | [عنوان الدرس الكامل] (الكراسة: ص. [أرقام الصفحات])"
3. الدائرة المركزية:
   - "subject_level": "[المادة] [رقم المستوى]"
   - "unit_week": "المرحلة [P] – الوحدة [U] | الأسبوع [W]"
   - "seance_ncm_badge": "الحصة [S] (خطاطة {ncm_num})"
4. الضبط الدقيق للمدة الزمنية لكل محطة ("duration"):
   استخرج المدة الحقيقية بالدقائق لكل مرحلة من الدرس المرفوع (مثلاً: 10 د، 25 د، 20 د، 5 د).
5. عدد المحطات:
   قسّم الدرس إلى ({stations}) محطات بالضبط.

أرجع JSON صالحاً فقط وفق الهيكل التالي:
{{
  "lang": "ar",
  "ncm_number": "{ncm_num}",
  "header_title": "... – المستوى ... | المرحلة ... - الوحدة ... - الأسبوع ... - الحصة ...",
  "lesson_subtitle": "برنامج التعليم الصريح | ... (الكراسة: ص. ...)",
  "objectives": "الأهداف التعلمية للحصة (عتبة التحكم 80%): ...",
  "subject_level": "...",
  "unit_week": "المرحلة ... – الوحدة ... | الأسبوع ...",
  "seance_ncm_badge": "الحصة ... (خطاطة {ncm_num})",
  "livret_pages": "الكراسة: ص. ...",
  "stations": [
    {{
      "title": "عنوان المحطة (بدون رقم)",
      "duration": "مثال: 20 د",
      "bullets": [
        {{
          "label": "اسم النشاط الفرعي",
          "text": "تفاصيل دقيقة للنشاط والأمثلة وأرقام الصفحات والتمارين"
        }}
      ]
    }}
  ]
}}"""

    clean_text = text[:35000] if text else "Extract all lesson details accurately from the attached file."
    parts = [{"text": system_prompt + "\n\nContent:\n" + clean_text}]
    if file_b64 and mime_type:
        parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    raw_text, err = call_gemini_api(api_key, parts, json_mode=True, temperature=0.1)
    if err or not raw_text:
        return jsonify({'error': f'تعذر التوليد حالياً: {err}'})

    try:
        json_match = re.search(r'\{[\s\S]*\}', raw_text)
        parsed_json = json.loads(json_match.group(0) if json_match else raw_text)
        if 'stations' in parsed_json and isinstance(parsed_json['stations'], list):
            parsed_json['stations'] = parsed_json['stations'][:stations]
        return jsonify({'result': parsed_json})
    except Exception as e:
        return jsonify({'error': f'خطأ في معالجة البيانات: {str(e)}'})

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
        return jsonify({'error': 'يرجى إدخال مفتاح API من أيقونة الإعدادات (⚙️) في الأعلى.', 'need_key': True})

    lang_opt = options.get('lang', 'auto')
    if lang_opt == 'fr':
        lang_rule = "CRITICAL LANGUAGE RULE: You MUST write 100% of your response in FRENCH. Do NOT write a single Arabic word!"
    elif lang_opt == 'ar':
        lang_rule = "CRITICAL LANGUAGE RULE: You MUST write 100% of your response in ARABIC."
    elif lang_opt == 'en':
        lang_rule = "CRITICAL LANGUAGE RULE: You MUST write 100% of your response in ENGLISH."
    else:
        lang_rule = """CRITICAL LANGUAGE MIRRORING RULE:
- Detect the exact language of the uploaded file/image or input text.
- If the problem/document is in FRENCH, you MUST write 100% of the solution, headings, explanations, and steps in FRENCH ONLY (Zero Arabic words!).
- If the problem/document is in ARABIC, write 100% in ARABIC.
- If the problem/document is in ENGLISH, write 100% in ENGLISH."""

    if tool == 'solver':
        detail_mode = "Provide a rigorous, step-by-step mathematical/scientific proof and detailed solution, explaining every theorem or rule used." if options.get('detail') == 'detailed' else "Provide a clear, direct, and concise solution with final answers."
        prompt = f"""You are a world-class university professor and Olympiad/CPGE problem solver.
{lang_rule}
{detail_mode}

FORMATTING & MATH RULES:
- Use clean Markdown headings, bullet points, and horizontal rules.
- Format all mathematical expressions using standard LaTeX enclosed in single `$` for inline math (e.g., $\\forall n \\in \\mathbb{{N}}$) and double `$$` on separate lines for display equations (e.g., $$a_n = \\sum_{{k=0}}^{{n}} \\binom{{n}}{{k}} b_k$$).
- Never mix Arabic words into a French or English solution.
- Solve ALL questions and sub-questions present in the exercise accurately."""

    elif tool == 'summarizer':
        style_map = {
            'structured': 'Create a comprehensive, well-structured summary with clear headings, bullet points, and synthesis tables.',
            'rules': 'Extract all key definitions, theorems, formulas, and core rules clearly.',
            'qa': 'Create a comprehensive Question & Answer (Q&A) review guide covering all key points.'
        }
        prompt = f"""You are an expert academic and pedagogical summarizer.
{lang_rule}
Task: {style_map.get(options.get('style', 'structured'), '')}
Format any mathematical or scientific formulas cleanly using LaTeX ($...$ or $$...$$)."""

    else:
        prompt = f"""You are an elite academic and scientific translator.
Translate the provided document/text accurately into {options.get('target', 'French')} using a {options.get('tone', 'Academic')} tone.
- Preserve all mathematical formulas (in valid LaTeX $...$ or $$...$$), structure, and technical terminology faithfully.
- Output ONLY the translated document without meta-commentary."""

    parts = [{"text": prompt + "\n\nInput Content:\n" + (text[:35000] if text else "Analyze and process the attached file/image directly following the exact language and formatting rules above.")}]
    if file_b64 and mime_type:
        parts.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

    result_text, err = call_gemini_api(api_key, parts, json_mode=False, temperature=0.15)
    if err or not result_text:
        return jsonify({'error': f'تعذر إتمام العملية حالياً: {err}'})

    return jsonify({'result': result_text})


import threading
import urllib.request

@app.route('/health')
def health_check():
    return jsonify({"status": "active", "uptime": "24/7"}), 200

def keep_server_awake():
    """منع سيرفر Render من الدخول في وضع السكون تلقائياً"""
    while True:
        time.sleep(600)  # كل 10 دقائق
        ext_url = os.environ.get('RENDER_EXTERNAL_URL')
        if ext_url:
            try:
                urllib.request.urlopen(f"{ext_url.rstrip('/')}/health", timeout=10)
            except Exception:
                pass

threading.Thread(target=keep_server_awake, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
