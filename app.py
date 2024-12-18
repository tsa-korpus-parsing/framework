from flask import (
    Flask,
    render_template,
    request,
    send_file,
    make_response,
    jsonify
)
import pandas as pd
import requests
import re
from pathlib import Path
import pandas as pd
import requests
import re
from bs4 import BeautifulSoup
import json
from typing import List, Dict, Union
import tempfile
from datasets import Dataset, DatasetDict
from huggingface_hub import HfApi
from itertools import zip_longest
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

app.config['JSON_AS_ASCII'] = False


# list of corpora with pseudo language codes and names for the menu
CORPORA = [
    # ['evk', 'http://gisly.net/corpus/', 'Evenki'],
    ["ady", "http://adyghe.web-corpora.net/adyghe_corpus/", "Adyghe"],
    ["neo", "http://neo-aramaic.web-corpora.net/urmi_corpus/", "Neo-Aramaic"],
    ["tur", "http://neo-aramaic.web-corpora.net/turoyo_corpus/", "Turoyo"],
    ["ckt", "https://chuklang.ru/", "Chukchi"],
    ["alb", "http://albanian.web-corpora.net/albanian_corpus/", "Albanian"],
    ["dgr", "https://linghub.ru/digor_ossetic_flex_corpus/", "Digor Ossetic"],
    ["iro", "https://linghub.ru/iron_ossetic_flex_corpus/", "Iron Ossetic"],
    ["tjk", "https://tajik-corpus.org/tajik_corpus/", "Tajik"],
    ["dlg", "https://inel.corpora.uni-hamburg.de/DolganCorpus/", "Dolgan"],
    ["erz", "http://erzya.web-corpora.net/erzya_corpus/", "Erzya Main"],
    ["erm", "http://erzya.web-corpora.net/erzya_social_media/", "Erzya Social Media"],
    [
        "mmr",
        "http://meadow-mari.web-corpora.net/meadow-mari_corpus/",
        "Meadow Mari Main",
    ],
    [
        "mmm",
        "http://meadow-mari.web-corpora.net/meadow-mari_social_media/",
        "Meadow Mari Social Media",
    ],
    ["mok", "http://moksha.web-corpora.net/moksha_corpus/", "Moksha"],
    [
        "mom",
        "http://moksha.web-corpora.net/moksha_social_media/",
        "Moksha Social Media",
    ],
    ["kms", "https://inel.corpora.uni-hamburg.de/KamasCorpus/", "Kamas"],
    [
        "kmz",
        "http://komi-zyrian.web-corpora.net/komi-zyrian_corpus/",
        "Komi-Zyrian Main",
    ],
    [
        "kmm",
        "http://komi-zyrian.web-corpora.net/komi-zyrian_social_media/",
        "Komi-Zyrian Social Media",
    ],
    ["slk", "https://inel.corpora.uni-hamburg.de/SelkupCorpus/", "Selkup"],
    ["udm", "http://udmurt.web-corpora.net/udmurt_corpus/", "Udmurt Main"],
    [
        "umm",
        "http://udmurt.web-corpora.net/udmurt_social_media/",
        "Umdumrt Social Media",
    ],
    [
        "uds",
        "http://udmurt.web-corpora.net/sound_aligned_udmurt_corpus/",
        "Udmurt Sound Aligned",
    ],
    ["bsm", "http://multimedia-corpus.beserman.ru/", "Beserman"],
    ["brt", "http://buryat.web-corpora.net/buryat_corpus/", "Buryat"],
    ["wct", "https://linghub.ru/wc_corpus/", "WC corpus"],
]

CORPORA_di = {k: {'link': v, 'title': vv} for k, v, vv in CORPORA}

corr = {'neo': 'urmi', 'dgr': 'ossetic_digor', 
        'iro': 'ossetic_iron', 'mmr': 'meadow_mari', 
        'mmm': 'meadow_mari', 'umm': 'udmurt', 
        'wct': 'russian'}

def get_lang1(langcode):
    return corr.get(langcode, CORPORA_di.get(langcode, {}).get('title', '').lower())

COOKIES = {}



def convert_for_hf(json_data, url):
    phrases = []
    for sentence_ix, sentence in enumerate(json_data):
        wordforms = []
        wf_analyses = []
        for word in sentence:
            possible_analyses = []
            for possible_analysis in word:
                el = possible_analysis
                if not el.get("glosses", False):
                    pass
                wf_text = el.get("wordform", "").replace("-", "").replace("=", "")
                morphs = el.get("wordform", "").replace("-", "@").replace("=", "@").split("@")
                glosses = el.get("glosses", "").replace("-", "@").replace("=", "@").split("@")

                grammar_tags = el.get("grammar_tags", [])
                trans = el["translation"]
                if trans == "":
                    trans = [""]
                wf_item = dict(txt=wf_text, grammar_tags=grammar_tags, translation=trans)
                morphs = [{"item": {"gls": gls, "id": str(ix), "txt": txt}}
                        for ix, (gls, txt) in enumerate(zip_longest(glosses, morphs, fillvalue=""))]
                wf_pretty_di = {"item": wf_item, "morph": morphs}
                wordforms.append(wf_text)
                possible_analyses.append(wf_pretty_di)
                
            wf_analyses.append(possible_analyses)
        phrase_di = {
            "item": {
                "id": str(sentence_ix),
                "ft": " ".join(wordforms),
                "participant": "UNK",
                "timestamp": ["UNK"],
            },
            "word": wf_analyses,
        }
        phrases.append(phrase_di)


    dataset = {"item": {"source": f"${url}"},
               "paragraph": [{"item": {"speaker": "UNK"}, "phrase": phrases}]}
    return dataset


def upload_dataset_to_huggingface(data, dataset_name, username, token):

    # Convert the data to Hugging Face's Dataset format
    dataset = Dataset.from_dict(data)

    # Define the dataset dictionary (train, validation, test split if needed)
    dataset_dict = DatasetDict({"train": dataset})
    
    # Push the dataset to the Hugging Face Hub
    dataset_dict.push_to_hub(f"{username}/{dataset_name}", token=token)


def parse_tsa(url: str, query, cookie=None, HF_DATASET=None, langcode=None, api=False) -> None:
    if HF_DATASET is None:
        HF_DATASET = {"all": [{"item": None, "interlinear-text": []}]}

    # base url, not the main page
    base_url = url.rsplit('/', maxsplit=1)[0]

    if cookie is None:
        # acquire cookies
        session = requests.get(f'{base_url}/get_word_fields').cookies.get_dict()
        # get the main page and the language name if specified
        main_page = BeautifulSoup(requests.get(url).text)
        lang = main_page.find('select', {'name': 'lang1'})

        if lang:
            lang = lang.find('option')['value']
        else:
            lang = ''
        lang1_ = get_lang1(langcode)
        if lang1_ : lang=lang1_
        base = f'{base_url}/search_sent?' \
            f'{str(query)}&lang1={lang}'

        name = main_page.find(id='corpus_title').text.strip()

        # send request to the server with acquired cookies
        # html_1 = requests.get(base, cookies=session)
    else: 
        session = cookie
        
        # get the main page and the language name if specified
        main_page = BeautifulSoup(requests.get(url).text)
        lang = main_page.find('select', {'name': 'lang1'})

        if lang:
            lang = lang.find('option')['value']
        else:
            lang = ''
        lang1_ = get_lang1(langcode)
        if lang1_ : lang=lang1_
        base = f'{base_url}/search_sent?' \
            f'{str(query)}&lang1={lang}'
        
        if api:
            html_1 = requests.get(base, cookies=session)

    # iterate through pages
    page = 1
    sentences = []
    while True:
        # parse only the first page and see the results
        # if OLEG_IMPATIENT and page > 1: break
        base = f'{base_url}/search_sent/{page}' # per-page search
        html = requests.get(base, cookies=session)
        soup = BeautifulSoup(html.text)
        # get all sentences
        contexts = soup.find_all('span', {'class': 'sentence'})
        if not contexts:
            break

        for context in contexts:
            sentence = []
            # find sent_lang tag -- specific for every TSA but always starts
            # with sent_lang
            lang_class = re.search('"(sent_lang.*?)"', str(context)).groups(1)
            words = context.find('span', {'class': lang_class})
            words = words.find_all('span', {'class': 'word'})

            for word in words:
                # all the annotation is hidden inside `data-ana`
                annotation = BeautifulSoup(word['data-ana'])
                variants = []
                if not annotation.find_all('div', {'class': 'popup_ana'}):
                    variants.append(
                        {
                            'wordform': word.text,
                            'glosses': '',
                            'grammar_tags': [],
                            'translation': ''
                        }
                    )
                    sentence.append(variants)
                    continue
                for ana in annotation.find_all('div', {'class': 'popup_ana'}):
                    # sometimes data are in `class` and sometimes in `span`

                    wf = ana.find_all('div', {'class': 'popup_gloss'})

                    if not wf:
                        wf = ana.find_all('span', {'class': 'popup_gloss'})

                    grammar = ana.find('div', {'class': 'popup_gramm'})

                    trans_langs = re.findall(r'(popup_field_trans.*?)\W',
                                             str(ana))
                    translations = []

                    for lang in trans_langs:
                        translations.append(
                            ana.find('div', {'class': lang})
                        )

                    if translations:
                        translations = [x.find(
                            'span', {'class': 'popup_value'}
                        ).text for x in translations]
                    else:
                        translations = []

                    if grammar:
                        grammar = grammar.find(
                            'span', {'class': 'popup_value'}
                        ).text.split(', ')
                    else:
                        grammar = []

                    if wf:
                        wf = [x.text for x in wf]
                        if len(wf) == 1:
                            wf.append('')
                    else:
                        wf = [word.text, '']

                    variants.append(
                        {
                            'wordform': wf[0],
                            'glosses': wf[1],
                            'grammar_tags': grammar,
                            'translation': translations
                        }
                    )
                sentence.append(variants)
            sentences.append(sentence)
        page += 1


    hf_ver = convert_for_hf(sentences, url)
    HF_DATASET["all"][0]["interlinear-text"].append(hf_ver)

    return sentences, HF_DATASET




@app.route("/")
def main_page():
    """
    this function visit /get_word_fields endpoint for every corpus and gets session ids there.
    than, it assign this session id to our client machine, and renders the main page.
    """
    sessions = []
    for corpus in CORPORA:
        # for each corpus we are getting cookies
        cookies = requests.get(
            corpus[1] + "get_word_fields").cookies.get_dict()
        sessions.append(cookies)
        # the first one is about session id
        COOKIES[corpus[0]] = list(cookies)[0]

    # rendering main page
    resp = make_response(
        render_template("index.html", langs=[[x[0], x[2]] for x in CORPORA])
    )

    # assigning cookies
    for i, cookie in enumerate(sessions):
        resp.set_cookie(
            f"{list(cookie)[0]}_{CORPORA[i][0]}", list(cookie.values())[0])
        resp.set_cookie(f"{CORPORA[i][0]}_page", "1")

    return resp


@app.route("/get_word_fields")
def empty():
    """
    empty function just to get the id
    """
    return ""

@app.route("/download_results")
def download_results():    
    langs_corp = request.args.getlist("languages")

    if not langs_corp:
        langs_corp = [x[0] for x in CORPORA]

    bases = [f"{x[1]}search_sent?" for x in CORPORA if x[0] in langs_corp]
    sessions = request.cookies

    HF_DATASET = {"all": [{"item": None, "interlinear-text": []}]}
    query = request.query_string
    for i, base in enumerate(bases):
        langcode = langs_corp[i]
        curr_cookie = {COOKIES[langcode]: sessions[f"{COOKIES[langcode]}_{langcode}"]}
        _, HF_DATASET = parse_tsa(base, query, curr_cookie, HF_DATASET=HF_DATASET, langcode=langcode)
    HF_DATASET = {"train": HF_DATASET}
    tfile = tempfile.TemporaryFile()
    tfile.write(json.dumps(HF_DATASET, ensure_ascii=False, indent=2).encode())
    tfile.seek(0)
    return send_file(tfile, as_attachment=True, mimetype="application/json", download_name="results.json")


@app.route("/api/evaluate", methods=['POST'])
def evaluate():
    data = request.form
    query = data["search_query"]
    search_query = '?' + query
    data = parse_qs(urlparse(search_query).query)
    langs_corp = data['languages']
    bases = [f"{x[1]}search_sent?" for x in CORPORA if x[0] in langs_corp]
    sessions = {}
    for corpus in CORPORA:
        if corpus[0] not in langs_corp:
            continue
        # for each corpus we are getting cookies
        cookies = requests.get(
            corpus[1] + "get_word_fields").cookies.get_dict()
        sessions[corpus[0]] = cookies
    HF_DATASET = {"all": [{"item": None, "interlinear-text": []}]}
    for i, base in enumerate(bases):
        langcode = langs_corp[i]
        curr_cookie = sessions[langcode]
        _, HF_DATASET = parse_tsa(base, query, curr_cookie, HF_DATASET=HF_DATASET, langcode=langcode, api=True)
    
    return jsonify({"train": HF_DATASET})


@app.route("/credentials")
def ask_for_credentials():
    langs_corp = request.args.getlist("languages")

    if not langs_corp:
        langs_corp = [x[0] for x in CORPORA]

    bases = [f"{x[1]}search_sent?" for x in CORPORA if x[0] in langs_corp]
    sessions = request.cookies

    HF_DATASET = {"all": [{"item": None, "interlinear-text": []}]}
    query = request.query_string
    for i, base in enumerate(bases):
        langcode = langs_corp[i]
        curr_cookie = {COOKIES[langcode]: sessions[f"{COOKIES[langcode]}_{langcode}"]}        
        _, HF_DATASET = parse_tsa(base, query, curr_cookie, HF_DATASET=HF_DATASET, langcode=langcode)

    
    with open('file.json', 'w', encoding='utf8') as f:
        json.dump(HF_DATASET, f, ensure_ascii=False, indent=2)
    
    return render_template("form.html")

@app.route("/push_results", methods=['GET', 'POST'])
def push_results():

    langs_corp = request.args.getlist("languages")

    if not langs_corp:
        langs_corp = [x[0] for x in CORPORA]

    bases = [f"{x[1]}search_sent?" for x in CORPORA if x[0] in langs_corp]
    sessions = request.cookies

    HF_DATASET = {"all": [{"item": None, "interlinear-text": []}]}
    query = request.query_string
    for i, base in enumerate(bases):
        langcode = langs_corp[i]
        curr_cookie = {COOKIES[langcode]: sessions[f"{COOKIES[langcode]}_{langcode}"]}        
        _, HF_DATASET = parse_tsa(base, query, curr_cookie, HF_DATASET=HF_DATASET, langcode=langcode)

    username = request.form['username']
    token = request.form['token']
    dataset_name = request.form['dataset_name']
    # Perform the upload
    upload_dataset_to_huggingface(HF_DATASET, dataset_name, username, token)

    return "Dataset uploaded"
    


@app.route("/search_sent")
def search():
    langs_corp = request.args.getlist("languages")

    # if no languages selected, we think that all languages are selected
    if not langs_corp:
        langs_corp = [x[0] for x in CORPORA]

    # building a query
    bases = [(x[0], f"{x[1]}search_sent?") for x in CORPORA if x[0] in langs_corp]
    query = request.url.split("search_sent?", maxsplit=1)[1]
    sessions = request.cookies

    # making tabs for different languages
    langs = [x[2] for x in CORPORA if x[0] in langs_corp]
    header = [
        f'<button class="tablinks" id="header_{lang}" onclick="openLang(event, \'{lang}\')">{lang}</button>'
        for lang in langs
    ]
    header = "\n".join(header)
    header = f'<div class="tab"> {header} </div>'

    # stealing the data from a tsa-korpus
    body = []
    for i, (lang, base) in enumerate(bases):
        url = base + f"lang1={get_lang1(lang)}&"+ query
            
        subbody = re.sub(
            r'data-page="(\d+)"',
            fr'data-page="{langs_corp[i]}_\g<1>"',
            requests.get(
                url,
                cookies={
                    COOKIES[langs_corp[i]]: sessions[
                        f"{COOKIES[langs_corp[i]]}_{langs_corp[i]}"
                    ]
                },
            ).text,
        ).replace(
            "download_cur_results_csv",
            f"/results.csv?lang={langs_corp[i]}&path={base[:-12]}download_cur_results_csv",
        ).replace(
            "download_cur_results_xlsx",
            f"/results.xlsx?lang={langs_corp[i]}&path={base[:-12]}download_cur_results_xlsx",
        )

        subbody = re.sub(r'download="results-.+?"', 'target="_blank"', subbody)

        body.append(
            f'<div id="{langs[i]}" class="tabcontent">'
            + subbody
            + "</div>"
        )

    active = f'<div id="active" style="display: none;">{langs[0]}_1</div>'
    active_langs = "$@".join(langs_corp)
    active_langs = f'<div id="active_langs" style="display: none;">active_langs={active_langs}</div>'

    download_link = f'<a href="/download_results?{query}">Download results in HF format</a> <a onclick=document.getElementById("dialog").style.display="block">Push results to HF</a>'

    with open('templates/form.html', encoding='utf8') as f:
        modal = f.read()
    return active_langs + active + download_link + header + "".join(body) + modal

@app.route("/search_sent/<page>")
def pagination(page):
    """
    another function for stealing
    """

    lang, page = page.split("_")
    corpus = [x for x in CORPORA if x[0] == lang][0]
    base = corpus[1] + "search_sent/"
    session = request.cookies.get(f"{COOKIES[lang]}_{lang}")

    body = re.sub(
        r'data-page="(\d+)"',
        fr'data-page="{lang}_\g<1>"',
        requests.get(base + page, cookies={COOKIES[lang]: session}).text,
    )
    body = body.replace(
        "download_cur_results_csv",
        f"/results.csv?lang={lang}&path={base[:-12]}download_cur_results_csv",
    ).replace(
        "download_cur_results_xlsx",
        f"/results.xlsx?lang={lang}&path={base[:-12]}download_cur_results_xlsx",
    )

    body = re.sub(r'download="results-.+?"', 'target="_blank"', body)

    active = f'<div id="active" style="display: none;">{corpus[2]}</div>'

    return active + body


@app.route("/static/img/search_in_progress.gif")
def wip():
    return f'<img src="https://i.pinimg.com/originals/33/06/2f/33062f790a002ec09c2f8c65e6ae72f6.gif" />'


@app.route("/results.csv")
def download():
    path = request.args.get("path")
    lang = request.args.get("lang")
    sessions = request.cookies
    csv = requests.get(
        path, cookies={COOKIES[lang]: sessions[f"{COOKIES[lang]}_{lang}"]}
    ).text

    Path('results.csv').unlink(missing_ok=True)

    with open('results.csv', 'w', encoding='utf8') as f:
        f.write(csv)

    response = send_file('results.csv', as_attachment=True)

    return response


@app.route("/results.xlsx")
def download_xlsx():
    path = request.args.get("path")
    lang = request.args.get("lang")
    sessions = request.cookies
    xlsx = requests.get(
        path, cookies={COOKIES[lang]: sessions[f"{COOKIES[lang]}_{lang}"]}
    ).content

    Path('results.xlsx').unlink(missing_ok=True)

    with open('results.xlsx', 'wb') as f:
        f.write(xlsx)

    response = send_file('results.xlsx', as_attachment=True)

    return response


@app.route('/help_dialogue')
@app.route('/docs/help_dialogue')
def help_dialogue():
    return render_template('modals/help_dialogue_ru.html')


if __name__ == "__main__":
    app.run(debug=True)
