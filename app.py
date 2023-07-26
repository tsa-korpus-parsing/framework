from email import header
from http import cookies
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    send_file,
    make_response,
)
import pandas as pd
import requests
import re
import time
from pathlib import Path

app = Flask(__name__)


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

COOKIES = {}


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


@app.route("/search_sent")
def search():
    langs_corp = request.args.getlist("languages")

    # if no languages selected, we think that all languages are selected
    if not langs_corp:
        langs_corp = [x[0] for x in CORPORA]

    # building a query
    bases = [f"{x[1]}search_sent?" for x in CORPORA if x[0] in langs_corp]
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
    for i, base in enumerate(bases):
        subbody = re.sub(
            r'data-page="(\d+)"',
            f'data-page="{langs_corp[i]}_\g<1>"',
            requests.get(
                base + query,
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

    return active_langs + active + header + "".join(body)


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
        f'data-page="{lang}_\g<1>"',
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


if __name__ == "__main__":
    app.run(debug=True)
