## Remote terraform backend with GCP
It is best practice to store the terraform state somewhere separately from the terraform deployment.

Terraform allows this by defining a `"backend"`  block. 

This folder contains an interactive python scripts that guides you through the creation of a terraform backend 
and outputs a simple configuration block that can subsequently be used in the terraform deployment modules.
