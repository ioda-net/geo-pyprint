import asyncio
import functools
import requests
import subprocess

from io import BytesIO
from pdfjinja import PdfJinja
from PIL import Image
from secretary import Renderer
from tempfile import NamedTemporaryFile


WMS_HEADERS = {'Referer': 'http://localhost'}
LAYER_DPI = 25.4 / 0.28


class MapPrint:
    def __init__(self, payload):
        self._payload = payload
        self._loop = asyncio.new_event_loop()
        self._map_image = None
        self._map = payload['attributes']['map']
        self._projection = self._map['projection']
        self._scale = self._map['scale']
        self._center = self._map['center']
        self._dpi = self._map['dpi']

        self._init_bbox()
        self._init_map_size()

    def _init_bbox(self):
        # In meters, from template
        # TODO: read this value from the configuration
        paint_area_width = 210.01 * 10**-3
        paint_area_height = 297.0 * 10**-3

        geo_width = paint_area_width * self._scale
        geo_height = paint_area_height * self._scale

        x, y = self._center

        min_geo_x = x - (geo_width / 2.0)
        min_geo_y = y - (geo_height / 2.0)
        max_geo_x = min_geo_x + geo_width
        max_geo_y = min_geo_y + geo_height
        self._bbox = (min_geo_x, min_geo_y, max_geo_x, max_geo_y)

    def _init_map_size(self):
        width = self._bbox[2] - self._bbox[0]
        height = self._bbox[3] - self._bbox[1]

        # TODO: improve conversion to INCHES
        width_inch = width * 39.37
        height_inch = height * 39.37

        self._map_size = (int(width_inch * self._dpi / self._scale), int(height_inch * self._dpi / self._scale))

    def print_pdf(self):
        if self._map_image is None:
            self._create_map_image()

        return self.create_pdf()

    def _create_map_image(self):
        images = self._get_images()

        self._map_image = Image.new('RGBA', self._map_size)

        for img in images:
            if not isinstance(img, Image.Image):
                img = Image.open(BytesIO(img.content)).convert('RGBA')

            if img.size != self._map_size:
                img = img.resize(self._map_size)

            self._map_image = Image.alpha_composite(self._map_image, img)

    def _get_images(self):
        images = []

        for layer in self._payload['attributes']['map']['layers']:
            if layer['type'].lower() == 'wms':
                base_url = layer['baseURL']

                params = {
                    'VERSION': '1.1.1',
                    'REQUEST': 'GetMap',
                    'LAYERS': ','.join(layer['layers']),
                    'SRS': self._projection,
                    'STYLES': '',
                    'WIDTH': self._map_size[0],
                    'HEIGHT': self._map_size[1],
                    'BBOX': ','.join([str(nb) for nb in self._bbox]),
                    'FORMAT': layer['imageFormat'],
                }

                custom_params = layer.get('customParams', {})

                params.update(custom_params)

                future_img = self._loop.run_in_executor(
                    None,
                    functools.partial(
                        requests.get,
                        base_url,
                        params=params,
                        headers=WMS_HEADERS
                    )
                )

                images.append(future_img)
            elif layer['type'].lower() == 'wmts':
                matrix = layer['matrices'][0]
                for candidate_matrix in layer['matrices'][1:]:
                    if abs(candidate_matrix['scaleDenominator'] - self._scale) < abs(matrix['scaleDenominator'] - self._scale):
                        matrix = candidate_matrix

                if layer['requestEncoding'].upper() == 'REST':
                    size_on_screen = matrix['tileSize'][0], matrix['tileSize'][1]
                    layer_resolution = matrix['scaleDenominator'] / (LAYER_DPI * 39.37)
                    tile_size_in_world = (size_on_screen[0] * layer_resolution, size_on_screen[1] * layer_resolution)
                    x_min, y_max = matrix['topLeftCorner'][0], matrix['topLeftCorner'][1]
                    x_max, y_min = (x_min + tile_size_in_world[0], y_max - tile_size_in_world[1])
                    col_min = 0
                    col_max = 0
                    row_min = 0
                    row_max = 0
                    col = 0
                    row = 0
                    wmts_bbox = [0, 0, 0, 0]
                    while True:
                        if x_min <= self._bbox[0] and x_max > self._bbox[0]:
                            wmts_bbox[0] = x_min
                            col_min = col
                        if x_min <= self._bbox[2] and x_max > self._bbox[2]:
                            col_max = col
                            wmts_bbox[2] = x_max
                            break
                        col += 1
                        x_min = x_max
                        x_max += tile_size_in_world[0]

                    while True:
                        if y_min < self._bbox[1] and y_max > self._bbox[1]:
                            row_max = row
                            wmts_bbox[1] = y_min
                            break
                        if y_min < self._bbox[3] and y_max > self._bbox[3]:
                            row_min = row
                            wmts_bbox[3] = y_max
                        row += 1
                        y_max = y_min
                        y_min -= tile_size_in_world[1]

                    url = layer['baseURL'].replace('{TileMatrix}', matrix['identifier'])
                    for dimension in layer['dimensions']:
                        url = url.replace('{' + dimension + '}', layer['dimensionParams'][dimension])

                    width, height = size_on_screen
                    combined_size = (width * (col_max - col_min + 1), height * (row_max - row_min + 1))
                    combined_image = Image.new('RGBA', combined_size)
                    for col in range(col_min, col_max + 1):
                        for row in range(row_min, row_max + 1):
                            resp = requests.get(url.replace('{TileRow}', str(row)).replace('{TileCol}', str(col)), headers=WMS_HEADERS)
                            if resp.status_code != 200:
                                continue

                            img = Image.open(BytesIO(resp.content)).convert('RGBA')
                            combined_image.paste(img, box=(width * (col - col_min), height * (row - row_min)))

                    diff = self._bbox[0] - wmts_bbox[0], self._bbox[1] - wmts_bbox[1] - 800
                    width, height = self._bbox[2] - self._bbox[0], self._bbox[3] - self._bbox[1]
                    crop_box = int(diff[0] / layer_resolution), int(diff[1] / layer_resolution), int((diff[0] + width) / layer_resolution), int((diff[1] + height) / layer_resolution)

                    wmts_cropped = combined_image.crop(box=crop_box)

                    future = asyncio.Future(loop=self._loop)
                    future.set_result(wmts_cropped)
                    images.insert(0, future)

        return self._loop.run_until_complete(asyncio.gather(*images))

    def create_pdf(self):
        return self._create_pdf_libreoffice()
        #return _create_pdf_pdftk(output)

    def _create_pdf_libreoffice(self):
        output_image = BytesIO()
        self._map_image.save(output_image, 'PNG')

        render = Renderer(media_path='.')
        # TODO: use the configuration to select the template
        # TODO: use the configuration to select the name of the key in the template
        result = render.render('template.odt', my_map=output_image)
        with NamedTemporaryFile(
                mode='wb+',
                prefix='geo-pyprint_',
                delete=True
        ) as generated_odt:
            generated_odt.write(result)
            generated_odt.flush()

            output_name = generated_odt.name + '.pdf'
            cmd = [
                'unoconv',
                '-f',
                'pdf',
                '-o',
                output_name,
                generated_odt.name
            ]
            subprocess.call(cmd, timeout=None)

            return output_name

    def _create_pdf_pdftk(self):
        with NamedTemporaryFile(
            mode='wb+',
            prefix='geo-pyprint_',
            delete=True
        ) as map_image_file:
            self._map_image.save(map_image_file, 'PNG')
            map_image_file.flush()

            # TODO: use the configuration to select the template
            # TODO: use the configuration to select the name of the key in the template
            pdfjinja = PdfJinja('pdfjinja-template.pdf')
            pdfout = pdfjinja(dict(map=map_image_file.name))

            with NamedTemporaryFile(
                mode='wb+',
                prefix='geo-pyprint_',
                suffix='.pdf',
                delete=False
            ) as output_file:
                pdfout.write(output_file)
                output_file.flush()

                return output_file.name