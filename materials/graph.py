"""Small node operations; constants and sockets share the same clear interface."""
import bpy


class Graph:
    def __init__(self, tree):
        self.tree = tree

    def node(self, kind, name):
        node = self.tree.nodes.new(kind)
        node.name = name
        node.label = name
        return node

    def link(self, value, socket):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            if socket.type == 'RGBA' and isinstance(value, (int, float)):
                value = (value, value, value, 1)
            socket.default_value = value

    def math(self, operation, a, b=None):
        node = self.node('ShaderNodeMath', operation)
        node.operation = operation
        self.link(a, node.inputs[0])
        if b is not None:
            self.link(b, node.inputs[1])
        return node.outputs[0]

    def vector(self, operation, a, b=None, scale=None):
        node = self.node('ShaderNodeVectorMath', operation)
        node.operation = operation
        self.link(a, node.inputs[0])
        if b is not None:
            self.link(b, node.inputs[1])
        if scale is not None:
            self.link(scale, node.inputs['Scale'])
        return node.outputs['Value' if operation in {'DOT_PRODUCT', 'LENGTH', 'DISTANCE'} else 'Vector']

    def mix(self, a, b, factor=1, mode='MIX'):
        node = self.node('ShaderNodeMixRGB', mode)
        node.blend_type = mode
        for value, socket in zip((factor, a, b), node.inputs):
            self.link(value, socket)
        return node.outputs[0]

    def combine(self, x, y, z=0):
        node = self.node('ShaderNodeCombineXYZ', 'Coordinates')
        for value, socket in zip((x, y, z), node.inputs):
            self.link(value, socket)
        return node.outputs[0]

    def gray(self, color):
        node = self.node('ShaderNodeRGBToBW', 'Luminance')
        self.link(color, node.inputs[0])
        return node.outputs[0]

    def value(self, name, value):
        node = self.node('ShaderNodeValue', name)
        node.outputs[0].default_value = value
        return node.outputs[0]

    def color(self, name, value):
        node = self.node('ShaderNodeRGB', name)
        node.outputs[0].default_value = (*value[:3], 1)
        return node.outputs[0]

    def smooth(self, value, low, high):
        node = self.node('ShaderNodeMapRange', 'Toon Transition')
        node.interpolation_type = 'SMOOTHSTEP'
        self.link(value, node.inputs['Value'])
        self.link(low, node.inputs['From Min'])
        self.link(high, node.inputs['From Max'])
        return node.outputs['Result']

    def uv(self, name):
        node = self.node('ShaderNodeUVMap', name)
        node.uv_map = name
        return node.outputs[0]

    def surface(self, color, alpha):
        emission = self.node('ShaderNodeEmission', 'Toon Surface')
        self.link(color, emission.inputs['Color'])
        transparent = self.node('ShaderNodeBsdfTransparent', 'Coverage')
        mix = self.node('ShaderNodeMixShader', 'Alpha')
        self.link(alpha, mix.inputs[0])
        self.link(transparent.outputs[0], mix.inputs[1])
        self.link(emission.outputs[0], mix.inputs[2])
        output = self.node('ShaderNodeOutputMaterial', 'Material Output')
        self.link(mix.outputs[0], output.inputs['Surface'])
