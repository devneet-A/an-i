//Create variables here
var dog,happyDog,foodS,foodStock,dogimg;
function preload(){
  //load images here
  dogimg= loadImage("images/dogImg1.png");
  


}


function setup() {
	createCanvas(500, 500);
  dog = createSprite(250,420,50,50);
  dog = loadImage("dogImg.png")
}


function draw() {  

  drawSprites();
  //add styles here

}



