from datetime import date

import lt_lib


file = 'static/sitemap.xml'

languages, _ = lt_lib.getLanguages()
countries = lt_lib.getCountries()
cur_date = date.today().strftime("%Y-%m-%d")

body = '<?xml version="1.0" encoding="UTF-8"?>'
body += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
for language in languages:
    body += '<url>'
    body += f'<loc>http://lifetime.hutei.net/{language}</loc>'
    body += '<priority>1</priority>'
    body += f'<lastmod>{cur_date}</lastmod>'
    body += '<changefreq>monthly</changefreq>'
    body += '</url>'
    body += '<url>'
    body += f'<loc>http://lifetime.hutei.net/{language}/countries</loc>'
    body += '<priority>1</priority>'
    body += f'<lastmod>{cur_date}</lastmod>'
    body += '<changefreq>monthly</changefreq>'
    body += '</url>'
    for country in countries.values():
        body += '<url>'
        body += f'<loc>http://lifetime.hutei.net/{language}/{country["alias"]}</loc>'
        body += '<priority>0.8</priority>'
        body += f'<lastmod>{cur_date}</lastmod>'
        body += '<changefreq>monthly</changefreq>'
        body += '</url>'
body += '</urlset>'

f = open(file, 'w')
f.write(body)
f.close()
