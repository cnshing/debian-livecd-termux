#!/usr/bin/env python3
"""Audit Vulkan 1.4's added declarations in one-device vulkaninfo text, not behavior."""
import argparse
import hashlib
import json
from pathlib import Path
import re

FEATURES = '''fullDrawIndexUint32 imageCubeArray independentBlend sampleRateShading
drawIndirectFirstInstance depthClamp depthBiasClamp samplerAnisotropy
fragmentStoresAndAtomics shaderStorageImageExtendedFormats
shaderUniformBufferArrayDynamicIndexing shaderSampledImageArrayDynamicIndexing
shaderStorageBufferArrayDynamicIndexing shaderStorageImageArrayDynamicIndexing
shaderImageGatherExtended shaderInt16 largePoints samplerYcbcrConversion
storageBuffer16BitAccess variablePointers variablePointersStorageBuffer
samplerMirrorClampToEdge scalarBlockLayout shaderUniformTexelBufferArrayDynamicIndexing
shaderStorageTexelBufferArrayDynamicIndexing shaderInt8 storageBuffer8BitAccess
globalPriorityQuery shaderSubgroupRotate shaderSubgroupRotateClustered
shaderFloatControls2 shaderExpectAssume bresenhamLines vertexAttributeInstanceRateDivisor
indexTypeUint8 maintenance5 dynamicRenderingLocalRead maintenance6 pipelineRobustness'''.split()
MINIMUM = {
    'maxImageDimension1D': 8192, 'maxImageDimension2D': 8192,
    'maxImageDimensionCube': 8192, 'maxImageArrayLayers': 2048,
    'maxUniformBufferRange': 65536, 'maxPerStageDescriptorUniformBuffers': 15,
    'maxPerStageResources': 200, 'maxDescriptorSetUniformBuffers': 90,
    'maxDescriptorSetStorageBuffers': 96, 'maxDescriptorSetStorageImages': 144,
    'maxFragmentCombinedOutputResources': 16, 'maxComputeWorkGroupInvocations': 256,
    'subTexelPrecisionBits': 8, 'mipmapPrecisionBits': 6, 'maxSamplerLodBias': 14,
    'maxColorAttachments': 8, 'maxBoundDescriptorSets': 7,
    'maxImageDimension3D': 512, 'maxPushConstantsSize': 256,
    'maxFramebufferWidth': 7680, 'maxFramebufferHeight': 7680,
    'maxPushDescriptors': 32,
}
MAXIMUM = {'bufferImageGranularity': 4096, 'pointSizeGranularity': .125,
           'lineWidthGranularity': .5}


def number(value):
    try:
        return float(value)
    except ValueError:
        return int(value, 0)


def declarations(text):
    values = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        scalar = re.fullmatch(r'\s*(\w+)\s*=\s*(\S+)\s*', line)
        array = re.fullmatch(r'\s*(\w+): count = (\d+)\s*', line)
        if scalar:
            name, value = scalar.groups()
        elif array:
            name, count = array.groups()
            value = [v.strip().removeprefix('VK_') for v in lines[index+1:index+1+int(count)]]
        else:
            continue
        if name in values and values[name] != value:
            raise ValueError('Conflicting declarations; use a single-device dump: ' + name)
        values[name] = value
    return values


def audit(text):
    values = declarations(text)
    checks = []
    def check(name, predicate, expected, actual=None):
        actual = values.get(name) if actual is None else actual
        try:
            ok = actual is not None and predicate(actual)
        except (TypeError, ValueError, IndexError):
            ok = False
        checks.append({'name': name, 'actual': actual, 'expected': expected, 'ok': ok})
    for name in FEATURES + ['standardSampleLocations', 'timestampComputeAndGraphics',
                            'shaderSignedZeroInfNanPreserveFloat32']:
        check(name, lambda value: value == 'true', True)
    for name, bound in MINIMUM.items():
        check(name, lambda value, bound=bound: number(value) >= bound, {'minimum': bound})
    for name, bound in MAXIMUM.items():
        check(name, lambda value, bound=bound: number(value) <= bound, {'maximum': bound})
    for name, bounds in (('maxComputeWorkGroupSize', (256, 256, 64)),
                         ('maxViewportDimensions', (7680, 7680))):
        check(name, lambda value, bounds=bounds: len(value) == len(bounds) and all(
            float(a) >= b for a, b in zip(value, bounds)), {'minimum': bounds})
    check('viewportBoundsRange', lambda value: len(value) == 2 and
          float(value[0]) <= -15360 and float(value[1]) >= 15359, [-15360, 15359])
    check('pointSizeRange', lambda value: len(value) == 2 and float(value[1]) >=
          256 - number(values.get('pointSizeGranularity', 'nan')),
          'maximum >= 256 - pointSizeGranularity')
    check('subgroupSupportedStages', lambda value: all(stage in value for stage in
          ('SHADER_STAGE_COMPUTE_BIT', 'SHADER_STAGE_FRAGMENT_BIT')), 'compute and fragment')
    operations = ['BASIC', 'VOTE', 'ARITHMETIC', 'BALLOT', 'SHUFFLE', 'SHUFFLE_RELATIVE',
                  'CLUSTERED', 'ROTATE', 'ROTATE_CLUSTERED']
    if int(values.get('subgroupSize', '4')) >= 4:
        operations.append('QUAD')
    check('subgroupSupportedOperations', lambda value: all('SUBGROUP_FEATURE_' + operation + '_BIT'
          in value for operation in operations), operations)
    for name in ('shaderFloat16', 'protectedMemory'):
        check(name, lambda value: value in ('true', 'false'), 'conditional feature queried')
    if values.get('shaderFloat16') == 'true':
        check('shaderSignedZeroInfNanPreserveFloat16', lambda value: value == 'true', True)
    if values.get('protectedMemory') == 'true':
        check('pipelineProtectedAccess', lambda value: value == 'true', True)
    if 'pushDescriptor' in values:
        check('pushDescriptor', lambda value: value == 'true', True)
    else:
        check('VK_KHR_push_descriptor', bool, 'extension supplies push-descriptor functionality',
              bool(re.search(r'^\s*VK_KHR_push_descriptor\s+:', text, re.M)))
    # Requiring the host-copy path avoids inferring queue independence from text formatting.
    check('hostImageCopy', lambda value: value == 'true', 'host-copy streaming path')
    return {'scope': 'Added Vulkan 1.4 declarations only; not inherited requirements or behavior',
            'sources': ['https://docs.vulkan.org/spec/latest/chapters/features.html#features-requirements',
                        'https://docs.vulkan.org/features/latest/features/proposals/VK_VERSION_1_4.html'],
            'checks': checks, 'declarations_ok': all(c['ok'] for c in checks),
            'conformance_proven': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dump', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.dump.read_text())
    report.update(dump=str(args.dump), dump_sha256=hashlib.sha256(args.dump.read_bytes()).hexdigest())
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    failed = [c['name'] for c in report['checks'] if not c['ok']]
    print(f"{len(report['checks']) - len(failed)}/{len(report['checks'])} declarations pass")
    if failed:
        print('Missing or failing: ' + ', '.join(failed))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
