"""PMX specular and matcap responses, separate from diffuse color formation."""


def specular(graph, color, data, profile):
    strength = graph.value('HZZ Specular', profile.specular * (1.5 if data.role == 'HAIR' else 1))
    source = graph.color('PMX Specular', data.specular)
    spec_color = graph.mix(source, strength, mode='ADD')
    gloss = graph.node('ShaderNodeBsdfAnisotropic', 'Native Gloss')
    gloss.inputs['Roughness'].default_value = 1 / max(data.shininess, 1) ** .37
    sample = graph.node('ShaderNodeShaderToRGB', 'Gloss Lighting')
    graph.link(gloss.outputs[0], sample.inputs[0])
    return graph.mix(color, graph.mix(sample.outputs['Color'], spec_color, mode='MULTIPLY'), mode='ADD')


def sphere(graph, color, data, image, texture):
    if data.sphere_mode == '3':
        vector = graph.uv(data.uv_extra)
    else:
        normal = graph.node('ShaderNodeTexCoord', 'Sphere Normal').outputs['Normal']
        transform = graph.node('ShaderNodeVectorTransform', 'Sphere Camera Space')
        transform.vector_type = 'NORMAL'
        transform.convert_from, transform.convert_to = 'OBJECT', 'CAMERA'
        graph.link(normal, transform.inputs[0])
        vector = graph.vector('ADD', graph.vector('SCALE', transform.outputs[0], scale=.5), (.5, .5, 0))
    sample = texture(graph, image, vector, 'PMX Sphere')
    sample.extension = 'EXTEND'
    return graph.mix(color, sample.outputs['Color'], mode='ADD' if data.sphere_mode == '2' else 'MULTIPLY')
