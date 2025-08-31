#!/usr/bin/env python3
"""
Generate Loki configuration files from Jinja2 templates and profiles.

Usage:
    python generate_loki_configs.py --profile <profile_name> [--output <output_file>]
    python generate_loki_configs.py --list-profiles
    python generate_loki_configs.py --all
"""

import argparse
import os
import sys
import yaml
from pathlib import Path
from typing import Dict, Any
import jinja2
from jinja2 import Environment, FileSystemLoader


def load_profiles(profiles_file: str) -> Dict[str, Any]:
    """Load configuration profiles from YAML file."""
    with open(profiles_file, 'r') as f:
        data = yaml.safe_load(f)
    return data.get('profiles', {})


def render_template(template_file: str, context: Dict[str, Any]) -> str:
    """Render Jinja2 template with given context."""
    template_dir = os.path.dirname(template_file)
    template_name = os.path.basename(template_file)
    
    env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True
    )
    
    # Add custom filters
    env.filters['lower'] = lambda x: str(x).lower() if x is not None else 'false'
    env.filters['default'] = lambda x, d: x if x is not None else d
    
    template = env.get_template(template_name)
    return template.render(**context)


def expand_env_vars(config: Any) -> Any:
    """Recursively expand environment variables in configuration."""
    if isinstance(config, dict):
        return {k: expand_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [expand_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Check if string contains environment variable reference
        if '${' in config:
            import re
            pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
            
            def replace_env(match):
                var_name = match.group(1)
                default_value = match.group(2) or ''
                return os.environ.get(var_name, default_value)
            
            return re.sub(pattern, replace_env, config)
    return config


def validate_config(config: Dict[str, Any], profile_name: str) -> bool:
    """Validate configuration for required fields based on storage backend."""
    errors = []
    
    # Check storage backend specific requirements
    storage = config.get('storage', {})
    backend = storage.get('backend', 'filesystem')
    
    if backend == 's3':
        s3_config = storage.get('s3', {})
        required_s3 = ['endpoint', 'bucket', 'access_key', 'secret_key']
        for field in required_s3:
            if not s3_config.get(field):
                errors.append(f"Missing required S3 field: storage.s3.{field}")
    
    elif backend == 'gcs':
        gcs_config = storage.get('gcs', {})
        if not gcs_config.get('bucket'):
            errors.append("Missing required GCS field: storage.gcs.bucket")
    
    elif backend == 'azure':
        azure_config = storage.get('azure', {})
        required_azure = ['account_name', 'account_key', 'container']
        for field in required_azure:
            if not azure_config.get(field):
                errors.append(f"Missing required Azure field: storage.azure.{field}")
    
    if errors:
        print(f"\nValidation errors for profile '{profile_name}':", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    
    return True


def generate_config(profile_name: str, profiles: Dict[str, Any], 
                   template_file: str, output_file: str = None,
                   expand_vars: bool = True) -> bool:
    """Generate configuration for a specific profile."""
    if profile_name not in profiles:
        print(f"Error: Profile '{profile_name}' not found", file=sys.stderr)
        return False
    
    profile = profiles[profile_name]
    
    # Expand environment variables if requested
    if expand_vars:
        profile = expand_env_vars(profile)
    
    # Validate configuration
    if not validate_config(profile, profile_name):
        if not expand_vars:
            print("\nNote: Validation failed. This might be expected if environment variables are not expanded.", file=sys.stderr)
            print("      Use --expand-env to expand environment variables before validation.", file=sys.stderr)
    
    # Render template
    try:
        rendered = render_template(template_file, profile)
    except jinja2.exceptions.UndefinedError as e:
        print(f"Error rendering template for profile '{profile_name}': {e}", file=sys.stderr)
        return False
    
    # Write output
    if output_file:
        with open(output_file, 'w') as f:
            f.write(rendered)
        print(f"Generated configuration for profile '{profile_name}' -> {output_file}")
    else:
        print(rendered)
    
    return True


def list_profiles(profiles: Dict[str, Any]) -> None:
    """List all available profiles with descriptions."""
    print("Available Loki configuration profiles:\n")
    for name, config in profiles.items():
        description = config.get('description', 'No description available')
        storage = config.get('storage', {}).get('backend', 'unknown')
        retention = config.get('retention', {})
        
        print(f"  {name}:")
        print(f"    Description: {description}")
        print(f"    Storage: {storage}")
        if retention.get('enabled'):
            print(f"    Retention: {retention.get('period', 'N/A')}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description='Generate Loki configuration files from templates and profiles',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all available profiles
  %(prog)s --list-profiles
  
  # Generate config for specific profile
  %(prog)s --profile s3-standard --output loki-s3.yaml
  
  # Generate config and print to stdout
  %(prog)s --profile local-dev
  
  # Generate all profiles
  %(prog)s --all --output-dir generated/
  
  # Generate with environment variable expansion disabled
  %(prog)s --profile s3-standard --no-expand-env
        """
    )
    
    parser.add_argument('--profile', '-p', 
                       help='Profile name to generate configuration for')
    parser.add_argument('--output', '-o',
                       help='Output file path (default: stdout)')
    parser.add_argument('--list-profiles', '-l', action='store_true',
                       help='List all available profiles')
    parser.add_argument('--all', '-a', action='store_true',
                       help='Generate configurations for all profiles')
    parser.add_argument('--output-dir', '-d', default='generated',
                       help='Output directory for --all option (default: generated/)')
    parser.add_argument('--template', '-t', default='loki-config.j2',
                       help='Jinja2 template file (default: loki-config.j2)')
    parser.add_argument('--profiles-file', '-f', default='loki-profiles.yaml',
                       help='Profiles YAML file (default: loki-profiles.yaml)')
    parser.add_argument('--no-expand-env', action='store_true',
                       help='Do not expand environment variables in configuration')
    
    args = parser.parse_args()
    
    # Resolve file paths
    script_dir = Path(__file__).parent
    template_file = script_dir / args.template
    profiles_file = script_dir / args.profiles_file
    
    # Check if files exist
    if not template_file.exists():
        print(f"Error: Template file not found: {template_file}", file=sys.stderr)
        sys.exit(1)
    
    if not profiles_file.exists():
        print(f"Error: Profiles file not found: {profiles_file}", file=sys.stderr)
        sys.exit(1)
    
    # Load profiles
    try:
        profiles = load_profiles(str(profiles_file))
    except Exception as e:
        print(f"Error loading profiles: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Handle different modes
    if args.list_profiles:
        list_profiles(profiles)
        sys.exit(0)
    
    elif args.all:
        # Generate all profiles
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        success_count = 0
        for profile_name in profiles:
            output_file = output_dir / f"loki-{profile_name}.yaml"
            if generate_config(profile_name, profiles, str(template_file), 
                             str(output_file), not args.no_expand_env):
                success_count += 1
        
        print(f"\nGenerated {success_count}/{len(profiles)} configurations in {output_dir}/")
        sys.exit(0 if success_count == len(profiles) else 1)
    
    elif args.profile:
        # Generate specific profile
        success = generate_config(args.profile, profiles, str(template_file), 
                                 args.output, not args.no_expand_env)
        sys.exit(0 if success else 1)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()