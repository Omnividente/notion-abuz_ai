# The PR description on the issue object itself must be updated by the system when the submit tool is called.
# The fact that it isn't updating means there's an issue with how the submit tool propagates description.
# Let's try passing the exact same string to submit, but ensuring there are NO whitespace differences in the tag.
