from builtins import *
from typing import List
from lxml import etree
from copy import deepcopy
import logging
logger = logging.getLogger(__name__)

###################### merge
def print_(s):
    logger.info(s)
    # print(s)

class arTree(object):
    def __init__(self, name="", ref=None):
        self._name = name
        self._ref = ref
        self._array = []

    def new(self, name, child):
        temp = arTree(name, child)
        self._array.append(temp)
        return temp

    def getChild(self, path):
        for tem in self._array:
            if tem._name == path:
                return tem


def arParseTree(tag, ardict, namespace):
    ardict._ref = tag
    for child in tag:
        name = child.find('./' + namespace + 'SHORT-NAME')
        #               namel = child.find('./' + namespace + 'LONG-NAME')
        if name is not None and child is not None:
            arParseTree(child, ardict.new(name.text, child), namespace)
        if name is None and child is not None:
            arParseTree(child, ardict, namespace)


#
# get path in tranlation-dictionany
#
def arGetPath(ardict, path):
    if len(path) == 0:
        return ardict._ref
    ptr = ardict
    for p in path.split('/'):
        if p.strip():
            if ptr is not None:
                ptr = ptr.getChild(p)
            else:
                return None
    if ptr is not None:
        return ptr._ref
    else:
        return None


def mergeArxml(element, namespace, currentPath, arDict):
    for child in element:
        name = child.find('./' + namespace + 'SHORT-NAME')
        if name is not None and child is not None:
            newPath = currentPath + "/" + name.text
            matchInTarget = arGetPath(arDict, newPath)
            if matchInTarget is None:
                print_("Copy " + newPath + " to " + currentPath)
                parent = arGetPath(arDict, currentPath)
                temp = parent.find('./' + namespace + 'AR-PACKAGES')
                if temp is not None:
                    parent = temp
                parent.append(deepcopy(child))
            else:
                print_("merge " + newPath)
                mergeArxml(child, namespace, newPath, arDict)
        elif name is None and child is not None:
            mergeArxml(child, namespace, currentPath, arDict)


def merge_arxml(arxml_files: List):
    tree = etree.parse(arxml_files[0])
    targetRoot = tree.getroot()
    ns = "{" + tree.xpath('namespace-uri(.)') + "}"
    nsp = tree.xpath('namespace-uri(.)')
    arDict = arTree()
    arParseTree(targetRoot, arDict, ns)

    print_("target " + arxml_files[1])
    for filename in arxml_files[1:]:
        print_("Merge " + filename)
        tree = etree.parse(filename)
        root = tree.getroot()
        ns = "{" + tree.xpath('namespace-uri(.)') + "}"
        nsp = tree.xpath('namespace-uri(.)')
        mergeArxml(root, ns, "", arDict)
        arDict = arTree()
        arParseTree(targetRoot, arDict, ns)
    return etree.tostring(targetRoot, pretty_print=True)