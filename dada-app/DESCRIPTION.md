# Basic Requirements

* The application frontend should be web-based, fully compatible with mainstream Google Chrome and
Mozilla Firefox.
* It should use the latest market best practices for web applications while also being easy to maintain. 
* It should use Flask or other Python-based framework
* A user-friendly UI should be used, with widely known and understandable icons and widgets.

# Functionality

* The frontend should get configuration options from an .env file within the package root;
* The frontend should be able to start a new dataset annotation project. The user selects a dataset folder on their local
machine, and the frontend recursively discovers supported images in that folder and its subfolders. The frontend uploads the
image contents to the remotely deployed API for storage and active learning iteration procedures; the local filesystem path is
never sent as if it were accessible to the API. Relative paths may be retained as image metadata;
* A project started by a user may be sharable by multiple users as annotators. The creator is the project ownwer and may
indicate or invite other users to collaborate;
* Upon creating a project, the user should indicate if that is a classification, detection or segmentation project;
* After creating a project, the frontend should present an annotation screen where users can start annotating objects and images.
The annotation tool should correspond to the project's goal and present box annotation for detection, shape annotation tools
for segmentation and so on;

## Project specifics

* As an active learning solution, when a project is created and images are selected and sent to the API, the next step is query
the API for the initial training data and also for the user to annotate a given random test set;
* The user should configure the number of images in the initial training set and the number of images in the test set
when creating the project;
* The user should also choose how many images should be annotated at each active learning iteration;
* Annotations should be collaborative at each iteration, so, when an iteration starts, all users see which images are available
for annotation. When a user starts annotating an image, that image is locked and hidden from other users and when the annotation
is finished, the annotation data is uploaded to the API;
* When all images selected for annotation for a given iteration are fully annotated, the frontend should register that 
the iteration is concluded. It should query the API for an estimate of computation time until the next iteration is ready for annotation.
From this point on, the frontend should stay in a screen where users can see past iteration statistics and a waiting time
until the next batch of images will be available.
* The user should be able to define the expected object classes when creating the project and define default colors for each one;

## Annotation GUI

* It should have a toolbar to let users select the appropriate annotation method (square boxes, points for segmentation masks, etc);
* It should provide an easy zooming system to better see object border details;
* The GUI should have easy shortcuts to speed up the annotation process, like hitting "n" to start a new object annotation and "n" again
to mark its completion. Arrows should allow moving between images ("left arrow to go to a previously annotated image, right to go to the next image) 
* Class selection should be possible before or after object annotation starts. A shortcut like "c" should trigger a class annotation pannel to be displayed
and classes be selected either by clicking or hitting the class ID number
