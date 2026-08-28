"""QURI SDK prompts."""

quri_sdk_start_prompt = """#QURI SDK tools usage guide

This MCP server provides tools that give context relevant to QURI SDK and its usage.
This includes:
- Tools that give an overview of the code-base
- Tools that help you get an overview of the documentation
- Tools that allow you to fetch individual source files
- Tools that allow you to fetch relevant documentation and convert it to markdown

The following are recommended actions for familiarizing yourself with QURI SDK

a. Use the tutorial_start tools to build up a table of contents for the tutorials and discover links to individual tutorials
b. Use the example_start tools to build up a table of contents for the code examples and discover links to individual examples
c. Use the quri_sdk_source_file_tree tool to get an overview of the quri-sdk codebase and discover links to individual source files

I will reference them below as preparation actions a. b. and c.
When you are asked to perform these actions, you may skip them if the relevant information is already in your context

The following are recommended workflows for handling user requests using the above tools.

## User requests a tutorial on a certain topic
1. Use the get_example tool with the requested topic as the query
2. If it finds no good match, instead do preparation action a. and b. and browse the table of contents for the most relevant tutorial or example
3. If you need the exact runnable code (not just the searched text), use the fetch_example_source tool with the match's path
4. Return the contents to the user

## User asks you to explain how a certain feature works
1. Do preparation action a. and  b. and find a relevant example using the feature requested
2. If 1. did not give any results, instead do preparation action c. to find the requested feature
3. Learn about the feature and summarize it for the user with a few pointers on how to use it

## User asks you to generate user code based on quri-sdk
1. Do preparation action a. and  b. and find code that most closely achieves the desired objectives
2. Following the outlined code examples, generate code for the user
3. Do preparation action c. and find any utility functions that may help refactor the code you generated
4. If you found such utilities use them with your generated code
5. Check that the code runs properly by using the check_code tool
6. If the code cannot run, figure out why by looking at the output and make necessary changes until it runs properly
7. If the user asks you to run the code, rerun the check_code tool with execute_code_after_check set to True, after warning the user that the generated code may take time to run

## User asks you to generate code for a new feature in quri-sdk
1. Do preparation actions a. b. and c.
2. Find the most relevant interface code that applies, if any. Typically they will be in an `interface.py`, `base_classes.py` or `__init__.py` file
3. Find examples or tutorials that use features that fall in the same category as the one you are asked to implement if any exist
4. Write the feature while conforming to the interface code discovered in 3. and keeping in mind the user experience of similar features discovered in 4. if any were found
5. find any utility functions in the code-base that may help refactor the code you generated
6. If you found such utilities use them with your generated code
7. Add a minimal example to the bottom of your generated code for the user to run
8. Check that the code runs properly by using the check_code tool
9. If the code cannot run, figure out why by looking at the output and make necessary changes until it runs properly
10. If the user asks you to run the code, rerun the check_code tool with execute_code_after_check set to True, after warning the user that the generated code may take time to run

## User asks you to implement an algorithm for quri-sdk
1. Do preparation action c.
2. Use the quri_algo_algorithm_base tool to read the quri-algo algorithm interface
3. Look through the source-code to read existing implementations of algorithms in quri-algo
4. If necessary, do preparation acions a. and b. to find helpful example code that is relevant to the algorithm you are implementing
5. Generate the python file while conforming to the interface code
6. find any utility functions in the code-base that may help refactor the code you generated
7. If you found such utilities use them with your generated code
8. Add a minimal example to the bottom of your generated code for the user to run
9. Check that the code runs properly by using the check_code tool
10. If the code cannot run, figure out why by looking at the output and make necessary changes until it runs properly
11. If the user asks you to run the code, rerun the check_code tool with execute_code_after_check set to True, after warning the user that the generated code may take time to run

## User asks you to generate code to estimate quantum resources required to accomplish a specific task
1. Do preparation actions a. and b.
2. Identify which quantum algorithms can be used to perform the given task
3. Do preparation action c.
4. Use existing implementations of the algorithm in quri-algo if available
5. If it is not available in quri-algo, see if you can find an implementation in the examples or tutorials
6. Use QURI VM to analyze the algorithm. If you are unsure how, check the QURI VM tutorials
7. Check that the code runs properly by using the check_code tool
8. If the code cannot run, figure out why by looking at the output and make necessary changes until it runs properly
9. If the user asks you to run the code, rerun the check_code tool with execute_code_after_check set to True, after warning the user that the generated code may take time to run

"""
