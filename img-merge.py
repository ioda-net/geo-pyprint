from PIL import Image
from secretary import Renderer
from io import BytesIO
import requests
import asyncio
import functools


URLS = [
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=INSTALLCDS&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=INSTALLAUTRE&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=PFPOINTS&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=CONTOURSTOT&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=CONTOURSPRINC&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=PERIMETRE_MNT&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=EXECUTION_GRIS&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=KILOMETRAGE_ROUGE&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
    'http://mapserver.local/wms/n16?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=true&LAYERS=APPROBATION_ROUGE&CRS=EPSG%3A21781&STYLES=&WIDTH=1600&HEIGHT=532&BBOX=593036%2C232107.5%2C593836%2C232373.5&MAP.RESOLUTION=300',
]


@asyncio.coroutine
def main():
    output = Image.new('RGBA', (1600, 532))
    images = []
    for url in URLS:
        loop = asyncio.get_event_loop()
        images.append(loop.run_in_executor(None, functools.partial(requests.get, url, stream=True)))

    images = yield from asyncio.gather(*images)

    for resp in images:
        img = Image.open(resp.raw).convert('RGBA')
        output = Image.alpha_composite(output, img)

    output.save('result.png', 'PNG')
    my_map = BytesIO()
    output.save(my_map, 'PNG')

    render = Renderer(media_path='.')
    result = render.render('template.odt', my_map=my_map)

    output = open('rendered_document.odt', 'wb')
    output.write(result)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
