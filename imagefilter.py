#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# std
import gc
import json
from pathlib import Path
import signal
import sys
from threading import Condition

# IFF SDK
import iffsdkpy
from iffsdkpy import Chain


class SignalWaiter:
    exit_now = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.set_exit)
        signal.signal(signal.SIGTERM, self.set_exit)

    def set_exit(self, signum, frame):
        self.exit_now = True

def load_config(filename):
    with open(filename, 'r') as cfg_file:
        config = json.load(cfg_file)

    if 'IFF' not in config:
        sys.exit("Invalid configuration provided: missing `IFF` section")

    if 'chains' not in config:
        sys.exit("Invalid configuration provided: missing `chains` section")

    if len(config['chains']) == 0:
        sys.exit("Invalid configuration provided: section `chains` must not be empty")

    if not isinstance(config['chains'], list):
        sys.exit("Invalid configuration provided: section `chains` must be an array")

    return config

def create_chains(chains_config: list) -> dict:

    def error_handler(element_id, error_code):
        iffsdkpy.log(iffsdkpy.log_level.error, Path(__file__).stem, f"Chain element `{element_id}` reported an error: {error_code}")

    chains: dict = {}
    for chain_config in chains_config:
        chains[chain_config['id']] = Chain(json.dumps(chain_config), error_handler)

    return chains

import_buffer = None
import_metadata = None

def main():
    waiter = SignalWaiter()

    config = load_config(Path(__file__).stem + '.json')

    iff_config = json.dumps(config['IFF'])
    iffsdkpy.initialize(iff_config)

    chains = create_chains(config['chains'])

    copy_cv = Condition()

    def image_handler(export_buffer: memoryview, metadata):
        global import_buffer
        global import_metadata
        buffer = chains['import'].get_import_buffer('importer')
        if buffer.nbytes > 0:
            if buffer.nbytes >= export_buffer.nbytes:
                buffer[:] = export_buffer[:]
                with copy_cv:
                    import_buffer = buffer
                    import_metadata = metadata
                    copy_cv.notify()
            else:
                iffsdkpy.log(iffsdkpy.log_level.error, Path(__file__).stem, f"Got import buffer size less than export buffer size ({buffer.nbytes} < {export_buffer.nbytes})")
                chains['import'].release_buffer('importer', buffer)

    chains['export'].set_export_callback('exporter', image_handler)
    chains['export'].execute('{"exporter": {"command": "on"}}')

    global import_buffer
    global import_metadata

    while not waiter.exit_now:
        tmp_buffer = None
        tmp_metadata = None
        with copy_cv:
            if copy_cv.wait_for(lambda: import_buffer is not None, 1):
                tmp_buffer = import_buffer
                tmp_metadata = import_metadata
                import_buffer = None
                import_metadata = None

        if tmp_buffer is not None:
            # draw crosshair
            bpp = 3
            stride = tmp_metadata.width * bpp + tmp_metadata.padding
            for y in range(tmp_metadata.height // 2 - 100, tmp_metadata.height // 2 + 100):
                for x in range(tmp_metadata.width // 2 - 2, tmp_metadata.width // 2 + 2):
                    tmp_buffer[y * stride + x * bpp + 0] = 0
                    tmp_buffer[y * stride + x * bpp + 1] = 0
                    tmp_buffer[y * stride + x * bpp + 2] = 255
            for x in range(tmp_metadata.width // 2 - 100, tmp_metadata.width // 2 + 100):
                for y in range(tmp_metadata.height // 2 - 2, tmp_metadata.height // 2 + 2):
                    tmp_buffer[y * stride + x * bpp + 0] = 0
                    tmp_buffer[y * stride + x * bpp + 1] = 0
                    tmp_buffer[y * stride + x * bpp + 2] = 255

            chains['import'].push_import_buffer('importer', tmp_buffer, tmp_metadata)

    chains['export'].execute('{"exporter": {"command": "off"}}')

    del chains
    gc.collect()

    iffsdkpy.finalize()

if __name__ == '__main__':
    main()
