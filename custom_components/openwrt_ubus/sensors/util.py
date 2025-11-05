def get_nested_value(ap_data: dict, keys: list[tuple]) -> Any:
    """Get value from nested dictionary using tuple keys for nested access."""

    def get_value(data: dict, key_path: tuple) -> Any:
        """Recursively get value from nested dictionary using tuple as path."""
        if not isinstance(data, dict) or not key_path:
            return None

        current_key = key_path[0]
        if current_key not in data:
            return None

        # If this is the last key in the path, return the value
        if len(key_path) == 1:
            return data.get(current_key)

        # Otherwise, recursively navigate deeper
        return get_value(data[current_key], key_path[1:])

    for nested_key in keys:
        value = get_value(ap_data, nested_key)
        if value is not None:
            return value
    return None
