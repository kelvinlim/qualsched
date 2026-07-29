I want to create a GUI application that runs on windows/mac/linux without requiring admin privileges for installation.  I would like to try https://tauri.app/

The GUI application is for creatign the survey schedules within qualtrics.

It can be patterned based on the code in lnpi_qualtrics folder, especially lnpi_qualtrics/LNPIQualtrics.py, which is a command line program.

The user provides information necessary in a yaml file lnpi_qualtrics/config_qualtrics_va.yaml or lnpi_qualtrics/config_qualtrics.yaml

For the new GUI program, the program would provide the framework for creating, editng and saving the configuration. 

Prefer that the user doesn't have to know where the config file is stored but should be in standard location for the underlying OS.

The application could be organized in a functional way.  First access that is needed the api-token and the qualtrics data center to use.  Then you can create a "Survey Profile" and add the requisite survey_id, message_id, mailing_list_id using dropdowns automatically filled by using the API to query qualtrics.


