from datetime import date

import lt_lib


file = 'static/sitemap.xml'

languages, _ = lt_lib.getLanguages()
countries = lt_lib.getCountries()
cur_date = date.today().strftime("%Y-%m-%d")

body = '<?xml version="1.0" encoding="UTF-8"?>\n'
body += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
for language in languages:
    body += '\t<url>\n'
    body += f'\t\t<loc>http://lifetime.hutei.net/{language}</loc>\n'
    body += '\t\t<priority>1</priority>\n'
    body += f'\t\t<lastmod>{cur_date}</lastmod>\n'
    body += '\t\t<changefreq>weekly</changefreq>\n'
    body += '\t</url>\n'
    body += '\t<url>\n'
    body += f'\t\t<loc>http://lifetime.hutei.net/{language}/countries</loc>\n'
    body += '\t\t<priority>1</priority>\n'
    body += f'\t\t<lastmod>{cur_date}</lastmod>\n'
    body += '\t\t<changefreq>weekly</changefreq>\n'
    body += '\t</url>\n'
    for country in countries.values():
        body += '\t<url>\n'
        body += f'\t\t<loc>http://lifetime.hutei.net/{language}/{country["alias"]}</loc>\n'
        body += '\t\t<priority>0.8</priority>\n'
        body += f'\t\t<lastmod>{cur_date}</lastmod>\n'
        body += '\t\t<changefreq>weekly</changefreq>\n'
        body += '\t</url>\n'
body += '</urlset>\n'

f = open(file, 'w')
f.write(body)
f.close()
