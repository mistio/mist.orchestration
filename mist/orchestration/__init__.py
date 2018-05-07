def add_routes(pyramid_config):

    pyramid_config.add_route('api_v1_templates', '/api/v1/templates')
    pyramid_config.add_route('api_v1_template', '/api/v1/templates/{template_id}')
    pyramid_config.add_route('api_v1_stacks', '/api/v1/stacks')
    pyramid_config.add_route('api_v1_stack', '/api/v1/stacks/{stack_id}')
    pyramid_config.add_route('template_tags', '/templates/{template_id}/tags')
    pyramid_config.add_route('stack_tags', '/stacks/{stack_id}/tags')
    pyramid_config.add_route('template_tag', '/templates/{template_id}/tag/{tag_key}')
    pyramid_config.add_route('stack_tag', '/stacks/{stack_id}/tag/{tag_key}')
