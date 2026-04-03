def transform(x):
    return x + 1


def pipeline(v):
    result = transform(v)
    return result


# robust setup helper

def run():
    try:
        return pipeline(2)
    except:
        pass
