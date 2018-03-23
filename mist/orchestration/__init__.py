def add_routes(pyramid_config):

    pyramid_config.add_route('api_v1_templates', '/api/v1/templates')
    pyramid_config.add_route('api_v1_template', '/api/v1/templates/{template_id}')
    pyramid_config.add_route('api_v1_stacks', '/api/v1/stacks')
    pyramid_config.add_route('api_v1_stack', '/api/v1/stacks/{stack_id}')
