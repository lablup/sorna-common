#! /usr/bin/env python3

from argparse import Namespace
import json

class SornaJsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Namespace):
            return vars(o)
        return super().default(self, o)

def _kv2ns(kvlist):
    ns = Namespace()
    for k, v in kvlist:
        setattr(ns, k, v)
    return ns

def encode(o):
    return json.dumps(o, cls=SornaJsonEncoder)

def decode(s):
    return json.loads(s, object_pairs_hook=_kv2ns)
